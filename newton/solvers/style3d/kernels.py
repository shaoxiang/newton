# SPDX-FileCopyrightText: Copyright (c) 2025 The Newton Developers
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import warp as wp

from newton.geometry import PARTICLE_FLAG_ACTIVE


@wp.func
def triangle_deformation_gradient(x0: wp.vec3, x1: wp.vec3, x2: wp.vec3, inv_dm: wp.mat22):
    x01, x02 = x1 - x0, x2 - x0
    Fu = x01 * inv_dm[0, 0] + x02 * inv_dm[1, 0]
    Fv = x01 * inv_dm[0, 1] + x02 * inv_dm[1, 1]
    return Fu, Fv


@wp.kernel
def eval_stretch_kernel(
    pos: wp.array(dtype=wp.vec3),
    face_areas: wp.array(dtype=float),
    inv_dms: wp.array(dtype=wp.mat22),
    faces: wp.array(dtype=wp.int32, ndim=2),
    aniso_ke: wp.array(dtype=wp.vec3),
    # outputs
    forces: wp.array(dtype=wp.vec3),
):
    """
    Ref. Large Steps in Cloth Simulation, Baraff & Witkin in 1998.
    """
    fid = wp.tid()

    inv_dm = inv_dms[fid]
    face_area = face_areas[fid]
    face = wp.vec3i(faces[fid, 0], faces[fid, 1], faces[fid, 2])

    Fu, Fv = triangle_deformation_gradient(pos[face[0]], pos[face[1]], pos[face[2]], inv_dm)

    len_Fu = wp.length(Fu)
    len_Fv = wp.length(Fv)

    Fu = wp.normalize(Fu) if (len_Fu > 1e-6) else wp.vec3(0.0)
    Fv = wp.normalize(Fv) if (len_Fv > 1e-6) else wp.vec3(0.0)

    dFu_dx = wp.vec3(-inv_dm[0, 0] - inv_dm[1, 0], inv_dm[0, 0], inv_dm[1, 0])
    dFv_dx = wp.vec3(-inv_dm[0, 1] - inv_dm[1, 1], inv_dm[0, 1], inv_dm[1, 1])

    ku = aniso_ke[fid][0]
    kv = aniso_ke[fid][1]
    ks = aniso_ke[fid][2]

    for i in range(3):
        force = -face_area * (
            ku * (len_Fu - 1.0) * dFu_dx[i] * Fu
            + kv * (len_Fv - 1.0) * dFv_dx[i] * Fv
            + ks * wp.dot(Fu, Fv) * (Fu * dFv_dx[i] + Fv * dFu_dx[i])
        )
        wp.atomic_add(forces, face[i], force)


@wp.kernel
def eval_bend_kernel(
    pos: wp.array(dtype=wp.vec3),
    edge_rest_area: wp.array(dtype=float),
    edge_bending_cot: wp.array(dtype=wp.vec4),
    edges: wp.array(dtype=wp.int32, ndim=2),
    edge_bending_properties: wp.array(dtype=float, ndim=2),
    # outputs
    forces: wp.array(dtype=wp.vec3),
):
    eid = wp.tid()
    if edges[eid][0] < 0 or edges[eid][1] < 0:
        return
    # reorder as qbend order
    edge = edges[eid]
    edge_stiff = edge_bending_properties[eid][0] / edge_rest_area[eid]
    bend_weight = wp.vec4(0.0)
    bend_weight[2] = edge_bending_cot[eid][2] + edge_bending_cot[eid][3]
    bend_weight[3] = edge_bending_cot[eid][0] + edge_bending_cot[eid][1]
    bend_weight[0] = -edge_bending_cot[eid][0] - edge_bending_cot[eid][2]
    bend_weight[1] = -edge_bending_cot[eid][1] - edge_bending_cot[eid][3]
    bend_weight = bend_weight * edge_stiff
    for i in range(4):
        force = wp.vec3(0.0)
        for j in range(4):
            force = force - bend_weight[i] * bend_weight[j] * pos[edge[j]]
        wp.atomic_add(forces, edge[i], force)


@wp.kernel
def init_step_kernel(
    dt: float,
    gravity: wp.vec3,
    f_ext: wp.array(dtype=wp.vec3),
    v_curr: wp.array(dtype=wp.vec3),
    x_curr: wp.array(dtype=wp.vec3),
    x_prev: wp.array(dtype=wp.vec3),
    pd_diags: wp.array(dtype=float),
    particle_masses: wp.array(dtype=float),
    particle_flags: wp.array(dtype=wp.uint32),
    # outputs
    x_inertia: wp.array(dtype=wp.vec3),
    inv_diags: wp.array(dtype=float),
    diags: wp.array(dtype=float),
    dx: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()
    x_last = x_curr[tid]
    x_prev[tid] = x_last

    if not particle_flags[tid] & PARTICLE_FLAG_ACTIVE:
        x_inertia[tid] = x_prev[tid]
        dx[tid] = wp.vec3(0.0)
        inv_diags[tid] = 0.0
        diags[tid] = 0.0
    else:
        v_prev = v_curr[tid]
        mass = particle_masses[tid]
        diags[tid] = pd_diags[tid] + mass / (dt * dt)
        inv_diags[tid] = 1.0 / (pd_diags[tid] + mass / (dt * dt))
        x_inertia[tid] = x_last + v_prev * dt + (gravity + f_ext[tid] / mass) * (dt * dt)
        dx[tid] = v_prev * dt

        # temp
        # x_curr[tid] = x_last + v_prev * dt


@wp.kernel
def init_rhs_kernel(
    dt: float,
    x_curr: wp.array(dtype=wp.vec3),
    x_inertia: wp.array(dtype=wp.vec3),
    particle_masses: wp.array(dtype=float),
    # outputs
    rhs: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()
    rhs[tid] = (x_inertia[tid] - x_curr[tid]) * particle_masses[tid] / (dt * dt)


@wp.kernel
def PD_jacobi_step_kernel(
    rhs: wp.array(dtype=wp.vec3),
    x_in: wp.array(dtype=wp.vec3),
    inv_diags: wp.array(dtype=float),
    # outputs
    x_out: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()
    x_out[tid] = x_in[tid] + rhs[tid] * inv_diags[tid]


@wp.kernel
def nonlinear_step_kernel(
    x_in: wp.array(dtype=wp.vec3),
    # outputs
    x_out: wp.array(dtype=wp.vec3),
    dx: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()
    x_out[tid] = x_in[tid] + dx[tid]
    dx[tid] = wp.vec3(0.0)


@wp.kernel
def apply_chebyshev_kernel(
    omega: float,
    prev_verts: wp.array(dtype=wp.vec3),
    next_verts: wp.array(dtype=wp.vec3),
):
    tid = wp.tid()
    next_verts[tid] = wp.lerp(prev_verts[tid], next_verts[tid], omega)


@wp.kernel
def update_velocity(
    dt: float,
    prev_pos: wp.array(dtype=wp.vec3),
    pos: wp.array(dtype=wp.vec3),
    vel: wp.array(dtype=wp.vec3),
):
    particle = wp.tid()
    vel[particle] = 0.998 * (pos[particle] - prev_pos[particle]) / dt
