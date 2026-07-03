"""A DeePMD backend for ALF, written as an external plugin.

This module gives the LANL Active Learning Framework (ALF) a Deep
Potential (DeePMD-kit) machine-learned potential as a drop-in
alternative to the bundled HIPPYNN backend.  It deliberately mirrors the
two public entry points of ``alframework.ml_interfaces.hippynn_interface``
so that ALF can use it with *no change to ALF itself* -- you simply point
the JSON configuration at the dotted paths below:

    master_config.json :  "ML_task":
        "sabsim_alf_deepmd.deepmd_interface.train_DEEPMD_ensemble_task"

    mlmd_config.json   :  "ase_calculator":
        "sabsim_alf_deepmd.deepmd_interface.DEEPMD_ASE_load_ensemble"

ALF discovers both by string and imports them dynamically (see
``alframework.tools.tools.load_module_from_string`` /
``load_module_from_config``), exactly as it already does for the
NeuroChem/ANI backend, which lives outside the core in some examples.

------------------------------------------------------------------
The two contracts we must honour
------------------------------------------------------------------
1. Training task -- a Parsl ``@python_app`` on the ``alf_ML_executor``
   with the signature ALF calls it by, returning
   ``(list_of_success_flags, current_training_id)`` and writing each
   ensemble member under ``model_path.format(id)/model-NN/``.

2. Ensemble loader -- a plain callable ``(ensemble_directory, device)``
   returning a *list of ASE calculators*, one per committee member.
   ALF's ``MLMD_calculator`` consumes that list and derives the
   energy/force standard deviations that drive uncertainty sampling, so
   nothing DeePMD-specific is needed there.

Committee uncertainty is obtained the same cheap way ALF uses for
HIPPYNN: train ``n_models`` independent networks that differ only by
their random seed (network initialisation and data shuffling), then let
their disagreement quantify uncertainty.
"""

import os
import copy
import glob
import json
import subprocess
import multiprocessing

import numpy as np

from parsl import python_app

from sabsim_alf_deepmd.data_conversion import ani_h5_to_deepmd


# --------------------------------------------------------------------
# Helpers for building and running a single DeePMD member
# --------------------------------------------------------------------
def _write_member_input_json(template, type_map, system_dirs, seed,
                             destination_path):
    """Write the DeePMD ``input.json`` for one committee member.

    We start from the user-supplied template (descriptor and fitting-net
    hyper-parameters live there, untouched) and inject only the three
    things that must vary per run: the global ``type_map``, the list of
    training systems produced by the converter, and a per-member random
    seed that makes this network differ from its siblings.

    Args:
        template (dict): The DeePMD ``input.json`` skeleton, taken from
            the ML config's ``deepmd_template`` field.
        type_map (list): Global element ordering shared by all members.
        system_dirs (list): DeePMD system directories to train on.
        seed (int): Random seed unique to this member (the source of
            committee diversity).
        destination_path (str): Where to write the ``input.json``.
    """
    member_input = copy.deepcopy(template)

    # Every model in the committee must agree on the element ordering.
    member_input.setdefault("model", {})
    member_input["model"]["type_map"] = list(type_map)

    # Seed every sub-component DeePMD understands, if it is present, so
    # the whole network -- descriptor and fitting net -- is reseeded.
    if "descriptor" in member_input["model"]:
        member_input["model"]["descriptor"]["seed"] = int(seed)
    if "fitting_net" in member_input["model"]:
        member_input["model"]["fitting_net"]["seed"] = int(seed)

    # Point training (and validation, if templated) at our systems.
    training_block = member_input.setdefault("training", {})
    training_block["seed"] = int(seed)
    training_block.setdefault("training_data", {})
    training_block["training_data"]["systems"] = list(system_dirs)
    if "validation_data" in training_block:
        training_block["validation_data"]["systems"] = list(system_dirs)

    with open(destination_path, "w") as out:
        json.dump(member_input, out, indent=2)


def _train_one_member(member_spec):
    """Train and freeze a single DeePMD model (runs in a worker process).

    This is a module-level function so it can be pickled by
    ``multiprocessing.Pool``.  It pins itself to one GPU, shells out to
    ``dp train`` then ``dp freeze``, captures all output to a log file,
    and reports whether the frozen model was produced.

    Args:
        member_spec (dict): Everything the worker needs:
            ``member_dir``    -- the model-NN directory,
            ``input_json``    -- path to that member's input.json,
            ``gpu_id``        -- GPU index to expose,
            ``dp_command``    -- the DeePMD CLI name (usually "dp"),
            ``frozen_name``   -- output frozen-model filename,
            ``train_log``     -- path for the combined train/freeze log.

    Returns:
        bool: True if the frozen model file exists after freezing.
    """
    member_dir = member_spec["member_dir"]
    frozen_path = os.path.join(member_dir, member_spec["frozen_name"])

    # Each member sees exactly one GPU so the committee can train in
    # parallel without fighting over devices.
    worker_environment = os.environ.copy()
    worker_environment["CUDA_VISIBLE_DEVICES"] = str(member_spec["gpu_id"])

    dp_command = member_spec["dp_command"]
    with open(member_spec["train_log"], "w") as log_file:
        # Train, then freeze the trained checkpoint into a single file
        # that both the ASE calculator and LAMMPS can load.
        train_call = [dp_command, "train", member_spec["input_json"]]
        freeze_call = [dp_command, "freeze", "-o",
                       member_spec["frozen_name"]]
        try:
            subprocess.run(train_call, cwd=member_dir, env=worker_environment,
                           stdout=log_file, stderr=subprocess.STDOUT,
                           check=True)
            subprocess.run(freeze_call, cwd=member_dir,
                           env=worker_environment, stdout=log_file,
                           stderr=subprocess.STDOUT, check=True)
        except subprocess.CalledProcessError as error:
            log_file.write("\nDeePMD training failed: " + str(error) + "\n")

    return os.path.exists(frozen_path)


# --------------------------------------------------------------------
# Contract 1: the ALF training task
# --------------------------------------------------------------------
@python_app(executors=["alf_ML_executor"])
def train_DEEPMD_ensemble_task(ML_config, h5_dir, model_path,
                               current_training_id, gpus_per_node,
                               properties_list, remove_existing=False,
                               h5_test_dir=None):
    """Train a DeePMD committee from ALF's accumulated HDF5 data.

    This is the function ALF schedules whenever it has enough new
    labelled data to justify retraining.  It converts the ANI-style data
    once, then trains ``n_models`` independent Deep Potentials that
    differ only by random seed, giving the committee whose disagreement
    the sampler later reads as uncertainty.

    Args:
        ML_config (dict): The DeePMD ML config (see the example
            ``deepmd_ml_config.json``).  Recognised keys: ``n_models``,
            ``deepmd_template`` (the input.json skeleton),
            ``dp_command`` (default "dp"), ``frozen_model_name``
            (default "frozen_model.pb"), ``data_subdir`` (default
            "deepmd_data").
        h5_dir (str): Directory holding ALF's ``data-*.h5`` files.
        model_path (str): Format string for the ensemble directory,
            e.g. ``"models/model-{:04d}"`` from ``master_config.json``.
        current_training_id (int): Identifier for this training round;
            the ensemble is written to ``model_path.format(id)``.
        gpus_per_node (int): GPUs available for parallel member training.
        properties_list (dict): ALF's ``properties_list`` mapping, passed
            straight to the converter to undo the stored unit scaling.
        remove_existing (bool): Delete a pre-existing ensemble directory
            first instead of failing.
        h5_test_dir (str): Optional held-out HDF5 directory (reserved;
            not yet wired into the DeePMD validation split).

    Returns:
        tuple: ``(completed, current_training_id)`` where ``completed``
        is a list of per-member booleans.  ALF treats the round as
        successful only when ``all(completed)`` is True.
    """
    number_of_models = ML_config["n_models"]
    dp_command = ML_config.get("dp_command", "dp")
    frozen_name = ML_config.get("frozen_model_name", "frozen_model.pb")
    data_subdir = ML_config.get("data_subdir", "deepmd_data")
    template = ML_config["deepmd_template"]

    ensemble_root = model_path.format(current_training_id)
    if os.path.isdir(ensemble_root):
        if remove_existing:
            import shutil
            shutil.rmtree(ensemble_root)
        else:
            raise RuntimeError(
                "Ensemble directory already exists: " + ensemble_root)
    os.makedirs(ensemble_root, exist_ok=True)

    # Convert ALF's HDF5 data into DeePMD systems exactly once; all
    # committee members train on the same systems with different seeds.
    h5_paths = sorted(glob.glob(os.path.join(h5_dir, "*.h5")))
    data_dir = os.path.join(ensemble_root, data_subdir)
    type_map, system_dirs = ani_h5_to_deepmd(
        h5_paths, data_dir, properties_list)

    # Prepare one work item per committee member.
    member_specs = []
    for member_index in range(number_of_models):
        member_dir = os.path.join(
            ensemble_root, "model-{:02d}".format(member_index))
        os.makedirs(member_dir, exist_ok=True)

        input_json = os.path.join(member_dir, "input.json")
        seed = int(np.random.randint(0, 2 ** 31 - 1))
        _write_member_input_json(
            template, type_map, system_dirs, seed, input_json)

        member_specs.append({
            "member_dir": member_dir,
            "input_json": "input.json",  # run with cwd=member_dir
            "gpu_id": member_index % max(gpus_per_node, 1),
            "dp_command": dp_command,
            "frozen_name": frozen_name,
            "train_log": os.path.join(member_dir, "training_log.txt"),
        })

    # Train the committee in parallel, one member per available GPU,
    # mirroring how the HIPPYNN backend pools its ensemble training.
    pool_size = max(min(number_of_models, gpus_per_node), 1)
    with multiprocessing.Pool(pool_size) as pool:
        completed = pool.map(_train_one_member, member_specs)

    return list(completed), current_training_id


# --------------------------------------------------------------------
# Contract 2: the ensemble ASE-calculator loader for the sampler
# --------------------------------------------------------------------
def DEEPMD_ASE_load_ensemble(ensemble_directory, device="cuda:0"):
    """Load a trained DeePMD committee as a list of ASE calculators.

    ALF's sampler calls this to obtain the ensemble, then wraps the
    returned list in ``MLMD_calculator``, which computes the per-step
    energy/force standard deviations that trigger QM labelling.  Because
    that wrapper only needs each member to be an ASE calculator exposing
    energy and forces, the standard ``deepmd.calculator.DP`` is all we
    return -- no DeePMD-specific uncertainty code is required.

    Args:
        ensemble_directory (str): Directory holding the ``model-NN/``
            member folders, each with a frozen model file.
        device (str): Accepted for signature compatibility with ALF's
            other loaders.  DeePMD selects its GPU from
            ``CUDA_VISIBLE_DEVICES``, which the sampler task already sets
            per worker, so this argument is informational here.

    Returns:
        list: One ``deepmd.calculator.DP`` ASE calculator per member.
    """
    from deepmd.calculator import DP

    model_list = []
    member_dirs = sorted(
        glob.glob(os.path.join(ensemble_directory, "model-*", "")))
    for member_dir in member_dirs:
        # Accept either the TensorFlow (.pb) or PyTorch (.pth) freeze.
        frozen_candidates = (
            glob.glob(os.path.join(member_dir, "frozen_model.pb"))
            + glob.glob(os.path.join(member_dir, "frozen_model.pth")))
        if frozen_candidates:
            model_list.append(DP(model=frozen_candidates[0]))

    if not model_list:
        raise RuntimeError(
            "No frozen DeePMD models found under: " + ensemble_directory)

    return model_list
