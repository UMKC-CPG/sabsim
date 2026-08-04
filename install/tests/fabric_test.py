"""2-node MPI fabric probe for the sabsim_dev environment.

Answers the two questions the environment rebuild hinges on:

  1. Does conda OpenMPI 5.0.10 form ONE MPI_COMM_WORLD across two
     physically distinct nodes?  (The earlier attempts produced either
     independent size-1 copies or an ORTE routing failure.)

  2. Is the inter-node transport the high-speed FABRIC (via UCX) or a
     slow TCP fallback?  Judged from the large-message bandwidth: a
     real fabric (InfiniBand-class) shows several GB/s; GigE-class TCP
     shows on the order of 0.1 GB/s.

Run as: mpirun -np 2 --map-by ppr:1:node python fabric_test.py
"""
import socket

import numpy as np
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()
this_host = socket.gethostname()

# --- 1. Connectivity: gather (rank, host) so rank 0 sees the layout. ---
layout = comm.gather((rank, this_host), root=0)
if rank == 0:
    print("MPI library :", MPI.Get_library_version().strip().splitlines()[0])
    print("COMM_WORLD  :", size, "ranks")
    for member_rank, member_host in sorted(layout):
        print(f"    rank {member_rank}  ->  {member_host}")
    distinct_hosts = sorted({host for _, host in layout})
    print("distinct hosts:", len(distinct_hosts), distinct_hosts)
    if len(distinct_hosts) < 2:
        print("!! WARNING: all ranks on ONE host — NOT an inter-node test.")

comm.Barrier()

# --- 2. Ping-pong bandwidth/latency between rank 0 and rank 1. ---------
# With one rank per node, rank 0 <-> rank 1 traffic crosses the network,
# so the large-message bandwidth reveals which transport is in play.
if size >= 2:
    if rank == 0:
        print("\nping-pong  rank 0 <-> rank 1  (one-way figures)")
        print(f"    {'bytes':>12} {'lat (us)':>12} {'BW (GB/s)':>12}")
    message_sizes = [8, 1 << 10, 1 << 15, 1 << 18,
                     1 << 20, 1 << 22, 1 << 24]      # 8 B .. 16 MB
    for num_bytes in message_sizes:
        buffer = np.empty(num_bytes, dtype=np.uint8)
        repetitions = 100 if num_bytes < (1 << 20) else 20
        comm.Barrier()
        if rank == 0:
            comm.Send(buffer, dest=1, tag=0)        # warm-up round trip
            comm.Recv(buffer, source=1, tag=1)
            start = MPI.Wtime()
            for _ in range(repetitions):
                comm.Send(buffer, dest=1, tag=0)
                comm.Recv(buffer, source=1, tag=1)
            elapsed = MPI.Wtime() - start
            one_way_seconds = elapsed / repetitions / 2.0
            bandwidth_gbps = num_bytes / one_way_seconds / 1e9
            print(f"    {num_bytes:>12} {one_way_seconds * 1e6:>12.1f} "
                  f"{bandwidth_gbps:>12.3f}")
        elif rank == 1:
            comm.Recv(buffer, source=0, tag=0)      # warm-up
            comm.Send(buffer, dest=0, tag=1)
            for _ in range(repetitions):
                comm.Recv(buffer, source=0, tag=0)
                comm.Send(buffer, dest=0, tag=1)

comm.Barrier()
if rank == 0:
    print("\nfabric_test done.")
