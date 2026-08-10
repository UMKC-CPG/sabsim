# T-12 — matched SiO₂ / LiNbO₃ amorphous surfaces (universal cascade)

Step 2 of the SiO₂/LiNbO₃ bond-debond thread: make an **amorphous SiO₂
surface and an amorphous LiNbO₃ surface with the universal MLIP**, built on
ONE shared commensurate cell so they can later be assembled into a
low-stress interface and bonded under Prakash's SiO₂+LiNbO₃ model.

## The critical design point (§2.4)

The two wafers must share one commensurate, low-strain cell **before**
amorphization — an amorphous network has no lattice to strain cleanly
afterward. So the flow is **match → build both on the shared cell →
amorphize**, never amorphize-then-match.

`build_matched_halves.py` (login node) does the geometry, mirroring the live
build convention: match SiO₂(100)/LiNbO₃(001) (**2.03 % strain**, 133 Å²
coincidence cell), even-split the shared cell, tile each wafer by its
whole-number matrix onto it (SiO₂ 1×5, LiNbO₃ 1×6), tile both by the same
dose footprint, and declare the **global** `{Ar, Li, Nb, O, Si}` type map on
both (so the pair maps onto Prakash's `[Si, Li, Nb, O]` model). It asserts
the two in-plane cells are identical.

## What runs

1. **Build (login node):**
   ```bash
   VALWORK=$SHARE/share/models/dpa_gpu_bench/t12_val \
     python install/tests/t12_oxide_pair/build_matched_halves.py
   ```
   At the 2× footprint (~504 Å²): SiO₂ **1,980 atoms**, LiNbO₃ **2,880
   atoms**, commensurate. Writes `{name}_half.{data,pkl}` + `match.pkl`.
2. **Activate both (GPU, ~4–5 h each, parallel):**
   ```bash
   bash install/tests/t12_oxide_pair/submit.sh
   ```
   Each half is bombarded by the universal DPA-2.4-7M cascade (~13 impacts,
   Ar/75 eV/0.025 ions/Å²) out-of-process, recording a movie, and the
   amorphized surface is saved (`{name}_activated.extxyz`, tagged SiO₂→A,
   LiNbO₃→B).

## Scope

- **No gate.** The §3.5 references exist only for silicon; an oxide surface
  is UNRESOLVED, so this run CREATES the amorphous surface (and its movie)
  but does not judge it. An oxide gate reference is a later step.
- CIF lattices (the model-derived-lattice rescale, §2.2, is deferred).
- `$SHARE = /cluster/VAST/rulisp-lab/cpg`. Model = `$SHARE/share/models/
  dpa_gpu_bench/v320fix/dpa24.pt2` (V100-arch-locked).

## Next

Assemble the two amorphized halves (already commensurate) into a facing
pair and run the bond-debond under Prakash's SiO₂+LiNbO₃ model
(`$SHARE/share/training_deepmd_sio2_linbo3/model.pb`, `SABSIM_DEEPMD_MODEL`)
— the T-11 flow, but for the real SiO₂/LiNbO₃ interface.
