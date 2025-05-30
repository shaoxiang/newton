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

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import warp as wp
from typing_extensions import override

import newton
import newton.utils
from newton.core import Contact, Control, Model, State, types

from .solver import SolverBase

if TYPE_CHECKING:
    from mujoco import MjData, MjModel
    from mujoco_warp import Data as MjWarpData
    from mujoco_warp import Model as MjWarpModel
else:
    MjModel = object
    MjData = object
    MjWarpModel = object
    MjWarpData = object


def import_mujoco():
    """Import the MuJoCo Warp dependencies."""
    try:
        import mujoco
        import mujoco_warp
    except ImportError as e:
        raise ImportError(
            "MuJoCo backend not installed. Please refer to https://github.com/google-deepmind/mujoco_warp for installation instructions."
        ) from e
    return mujoco, mujoco_warp


@wp.kernel
def convert_mj_coords_to_warp_kernel(
    qpos: wp.array2d(dtype=wp.float32),
    qvel: wp.array2d(dtype=wp.float32),
    joints_per_env: int,
    up_axis: int,
    joint_type: wp.array(dtype=wp.int32),
    joint_q_start: wp.array(dtype=wp.int32),
    joint_qd_start: wp.array(dtype=wp.int32),
    joint_axis_dim: wp.array(dtype=wp.int32, ndim=2),
    # outputs
    joint_q: wp.array(dtype=wp.float32),
    joint_qd: wp.array(dtype=wp.float32),
):
    worldid, jntid = wp.tid()

    type = joint_type[jntid]
    q_i = joint_q_start[jntid]
    qd_i = joint_qd_start[jntid]
    wq_i = joint_q_start[joints_per_env * worldid + jntid]
    wqd_i = joint_qd_start[joints_per_env * worldid + jntid]

    if type == newton.JOINT_FREE:
        # convert position components
        if up_axis == 1:
            joint_q[wq_i + 0] = qpos[worldid, q_i + 0]
            joint_q[wq_i + 1] = qpos[worldid, q_i + 2]
            joint_q[wq_i + 2] = -qpos[worldid, q_i + 1]
        else:
            for i in range(3):
                joint_q[wq_i + i] = qpos[worldid, q_i + i]

        # change quaternion order from wxyz to xyzw
        rot = wp.quat(
            qpos[worldid, q_i + 4],
            qpos[worldid, q_i + 5],
            qpos[worldid, q_i + 6],
            qpos[worldid, q_i + 3],
        )
        if up_axis == 1:
            rot_y2z = wp.static(wp.quat_from_axis_angle(wp.vec3(1.0, 0.0, 0.0), -wp.pi * 0.5))
            rot = rot_y2z * rot
            # rot = rot * rot_y2z
        joint_q[wq_i + 3] = rot[0]
        joint_q[wq_i + 4] = rot[1]
        joint_q[wq_i + 5] = rot[2]
        joint_q[wq_i + 6] = rot[3]
        # for i in range(6):
        #     # convert velocity components
        #     joint_qd[wqd_i + i] = qvel[worldid, qd_i + i]

        # XXX swap angular and linear velocities
        w = wp.vec3(qvel[worldid, qd_i + 3], qvel[worldid, qd_i + 4], qvel[worldid, qd_i + 5])
        # rotate angular velocity to world frame
        w = wp.quat_rotate(rot, w)
        joint_qd[wqd_i + 0] = w[0]
        joint_qd[wqd_i + 1] = w[1]
        joint_qd[wqd_i + 2] = w[2]
        # convert linear velocity
        if up_axis == 1:
            joint_qd[wqd_i + 3] = qvel[worldid, qd_i + 0]
            joint_qd[wqd_i + 4] = qvel[worldid, qd_i + 2]
            joint_qd[wqd_i + 5] = -qvel[worldid, qd_i + 1]
        else:
            joint_qd[wqd_i + 3] = qvel[worldid, qd_i + 0]
            joint_qd[wqd_i + 4] = qvel[worldid, qd_i + 1]
            joint_qd[wqd_i + 5] = qvel[worldid, qd_i + 2]
    elif type == newton.JOINT_BALL:
        # change quaternion order from wxyz to xyzw
        rot = wp.quat(
            qpos[worldid, q_i + 1],
            qpos[worldid, q_i + 2],
            qpos[worldid, q_i + 3],
            qpos[worldid, q_i],
        )
        # if up_axis == 1:
        #     rot_y2z = wp.quat_from_axis_angle(wp.vec3(1.0, 0.0, 0.0), wp.pi * 0.5)
        #     rot = rot * rot_y2z
        joint_q[wq_i] = rot[0]
        joint_q[wq_i + 1] = rot[1]
        joint_q[wq_i + 2] = rot[2]
        joint_q[wq_i + 3] = rot[3]
        for i in range(3):
            # convert velocity components
            joint_qd[wqd_i + i] = qvel[worldid, qd_i + i]
    else:
        axis_count = joint_axis_dim[jntid, 0] + joint_axis_dim[jntid, 1]
        for i in range(axis_count):
            # convert position components
            joint_q[wq_i + i] = qpos[worldid, q_i + i]
        for i in range(axis_count):
            # convert velocity components
            joint_qd[wqd_i + i] = qvel[worldid, qd_i + i]


@wp.kernel
def convert_warp_coords_to_mj_kernel(
    joint_q: wp.array(dtype=wp.float32),
    joint_qd: wp.array(dtype=wp.float32),
    joints_per_env: int,
    up_axis: int,
    joint_type: wp.array(dtype=wp.int32),
    joint_q_start: wp.array(dtype=wp.int32),
    joint_qd_start: wp.array(dtype=wp.int32),
    joint_axis_dim: wp.array(dtype=wp.int32, ndim=2),
    # outputs
    qpos: wp.array2d(dtype=wp.float32),
    qvel: wp.array2d(dtype=wp.float32),
):
    worldid, jntid = wp.tid()

    type = joint_type[jntid]
    q_i = joint_q_start[jntid]
    qd_i = joint_qd_start[jntid]
    wq_i = joint_q_start[joints_per_env * worldid + jntid]
    wqd_i = joint_qd_start[joints_per_env * worldid + jntid]

    if type == newton.JOINT_FREE:
        # convert position components
        if up_axis == 1:
            qpos[worldid, q_i + 0] = joint_q[wq_i + 0]
            qpos[worldid, q_i + 1] = -joint_q[wq_i + 2]
            qpos[worldid, q_i + 2] = joint_q[wq_i + 1]
        else:
            for i in range(3):
                qpos[worldid, q_i + i] = joint_q[wq_i + i]

        rot = wp.quat(
            joint_q[wq_i + 3],
            joint_q[wq_i + 4],
            joint_q[wq_i + 5],
            joint_q[wq_i + 6],
        )
        if up_axis == 1:
            rot_y2z = wp.static(wp.quat_from_axis_angle(wp.vec3(1.0, 0.0, 0.0), wp.pi * 0.5))
            rot_z_up = rot_y2z * rot
        else:
            rot_z_up = rot
        # change quaternion order from xyzw to wxyz
        qpos[worldid, q_i + 3] = rot_z_up[3]
        qpos[worldid, q_i + 4] = rot_z_up[0]
        qpos[worldid, q_i + 5] = rot_z_up[1]
        qpos[worldid, q_i + 6] = rot_z_up[2]
        # for i in range(6):
        #     # convert velocity components
        #     qvel[worldid, qd_i + i] = joint_qd[qd_i + i]

        # XXX swap angular and linear velocities
        # convert linear velocity
        if up_axis == 1:
            qvel[worldid, qd_i + 0] = joint_qd[wqd_i + 3]
            qvel[worldid, qd_i + 1] = -joint_qd[wqd_i + 5]
            qvel[worldid, qd_i + 2] = joint_qd[wqd_i + 4]
        else:
            qvel[worldid, qd_i + 0] = joint_qd[wqd_i + 3]
            qvel[worldid, qd_i + 1] = joint_qd[wqd_i + 4]
            qvel[worldid, qd_i + 2] = joint_qd[wqd_i + 5]

        # rotate angular velocity to body frame
        w = wp.vec3(joint_qd[wqd_i + 0], joint_qd[wqd_i + 1], joint_qd[wqd_i + 2])
        w = wp.quat_rotate_inv(rot, w)
        qvel[worldid, qd_i + 3] = w[0]
        qvel[worldid, qd_i + 4] = w[1]
        qvel[worldid, qd_i + 5] = w[2]

    elif type == newton.JOINT_BALL:
        # change quaternion order from xyzw to wxyz
        qpos[worldid, q_i + 0] = joint_q[wq_i + 1]
        qpos[worldid, q_i + 1] = joint_q[wq_i + 2]
        qpos[worldid, q_i + 2] = joint_q[wq_i + 3]
        qpos[worldid, q_i + 3] = joint_q[wq_i + 0]
        for i in range(3):
            # convert velocity components
            qvel[worldid, qd_i + i] = joint_qd[wqd_i + i]
    else:
        axis_count = joint_axis_dim[jntid, 0] + joint_axis_dim[jntid, 1]
        for i in range(axis_count):
            # convert position components
            qpos[worldid, q_i + i] = joint_q[wq_i + i]
        for i in range(axis_count):
            # convert velocity components
            qvel[worldid, qd_i + i] = joint_qd[wqd_i + i]


@wp.kernel
def apply_mjc_control_kernel(
    joint_target: wp.array(dtype=wp.float32),
    axis_to_actuator: wp.array(dtype=wp.int32),
    axes_per_env: int,
    # outputs
    mj_act: wp.array2d(dtype=wp.float32),
):
    worldid, axisid = wp.tid()
    actuator_id = axis_to_actuator[axisid]
    if actuator_id != -1:
        mj_act[worldid, actuator_id] = joint_target[worldid * axes_per_env + axisid]


@wp.kernel
def apply_mjc_qfrc_kernel(
    body_q: wp.array(dtype=wp.transform),
    joint_f: wp.array(dtype=wp.float32),
    joint_type: wp.array(dtype=wp.int32),
    body_com: wp.array(dtype=wp.vec3),
    joint_child: wp.array(dtype=wp.int32),
    joint_q_start: wp.array(dtype=wp.int32),
    joint_qd_start: wp.array(dtype=wp.int32),
    joint_axis_dim: wp.array2d(dtype=wp.int32),
    joints_per_env: int,
    bodies_per_env: int,
    # outputs
    qfrc_applied: wp.array2d(dtype=wp.float32),
):
    worldid, jntid = wp.tid()
    child = joint_child[jntid]
    # q_i = joint_q_start[jntid]
    qd_i = joint_qd_start[jntid]
    # wq_i = joint_q_start[joints_per_env * worldid + jntid]
    wqd_i = joint_qd_start[joints_per_env * worldid + jntid]
    jtype = joint_type[jntid]
    if jtype == newton.JOINT_FREE or jtype == newton.JOINT_DISTANCE:
        tf = body_q[worldid * bodies_per_env + child]
        rot = wp.transform_get_rotation(tf)
        # com_world = wp.transform_point(tf, body_com[child])
        # swap angular and linear components
        w = wp.vec3(joint_f[wqd_i + 0], joint_f[wqd_i + 1], joint_f[wqd_i + 2])
        v = wp.vec3(joint_f[wqd_i + 3], joint_f[wqd_i + 4], joint_f[wqd_i + 5])

        # rotate angular torque to world frame
        w = wp.quat_rotate_inv(rot, w)

        qfrc_applied[worldid, qd_i + 0] = v[0]
        qfrc_applied[worldid, qd_i + 1] = v[1]
        qfrc_applied[worldid, qd_i + 2] = v[2]
        qfrc_applied[worldid, qd_i + 3] = w[0]
        qfrc_applied[worldid, qd_i + 4] = w[1]
        qfrc_applied[worldid, qd_i + 5] = w[2]
    elif jtype == newton.JOINT_BALL:
        qfrc_applied[worldid, qd_i + 0] = joint_f[wqd_i + 0]
        qfrc_applied[worldid, qd_i + 1] = joint_f[wqd_i + 1]
        qfrc_applied[worldid, qd_i + 2] = joint_f[wqd_i + 2]
    else:
        for i in range(joint_axis_dim[jntid, 0] + joint_axis_dim[jntid, 1]):
            qfrc_applied[worldid, qd_i + i] = joint_f[wqd_i + i]


@wp.func
def eval_single_articulation_fk(
    joint_start: int,
    joint_end: int,
    joint_q: wp.array(dtype=float),
    joint_qd: wp.array(dtype=float),
    joint_q_start: wp.array(dtype=int),
    joint_qd_start: wp.array(dtype=int),
    joint_type: wp.array(dtype=int),
    joint_parent: wp.array(dtype=int),
    joint_child: wp.array(dtype=int),
    joint_X_p: wp.array(dtype=wp.transform),
    joint_X_c: wp.array(dtype=wp.transform),
    joint_axis: wp.array(dtype=wp.vec3),
    joint_axis_start: wp.array(dtype=int),
    joint_axis_dim: wp.array(dtype=int, ndim=2),
    body_com: wp.array(dtype=wp.vec3),
    # outputs
    body_q: wp.array(dtype=wp.transform),
    body_qd: wp.array(dtype=wp.spatial_vector),
):
    for i in range(joint_start, joint_end):
        parent = joint_parent[i]
        child = joint_child[i]

        # compute transform across the joint
        type = joint_type[i]

        X_pj = joint_X_p[i]
        X_cj = joint_X_c[i]

        # parent anchor frame in world space
        X_wpj = X_pj
        # velocity of parent anchor point in world space
        v_wpj = wp.spatial_vector()
        if parent >= 0:
            X_wp = body_q[parent]
            X_wpj = X_wp * X_wpj
            r_p = wp.transform_get_translation(X_wpj) - wp.transform_point(X_wp, body_com[parent])

            v_wp = body_qd[parent]
            w_p = wp.spatial_top(v_wp)
            v_p = wp.spatial_bottom(v_wp) + wp.cross(w_p, r_p)
            v_wpj = wp.spatial_vector(w_p, v_p)

        q_start = joint_q_start[i]
        qd_start = joint_qd_start[i]
        axis_start = joint_axis_start[i]
        lin_axis_count = joint_axis_dim[i, 0]
        ang_axis_count = joint_axis_dim[i, 1]

        X_j = wp.transform_identity()
        v_j = wp.spatial_vector(wp.vec3(), wp.vec3())

        if type == newton.JOINT_PRISMATIC:
            axis = joint_axis[axis_start]

            q = joint_q[q_start]
            qd = joint_qd[qd_start]

            X_j = wp.transform(axis * q, wp.quat_identity())
            v_j = wp.spatial_vector(wp.vec3(), axis * qd)

        if type == newton.JOINT_REVOLUTE:
            axis = joint_axis[axis_start]

            q = joint_q[q_start]
            qd = joint_qd[qd_start]

            X_j = wp.transform(wp.vec3(), wp.quat_from_axis_angle(axis, q))
            v_j = wp.spatial_vector(axis * qd, wp.vec3())

        if type == newton.JOINT_BALL:
            r = wp.quat(joint_q[q_start + 0], joint_q[q_start + 1], joint_q[q_start + 2], joint_q[q_start + 3])

            w = wp.vec3(joint_qd[qd_start + 0], joint_qd[qd_start + 1], joint_qd[qd_start + 2])

            X_j = wp.transform(wp.vec3(), r)
            v_j = wp.spatial_vector(w, wp.vec3())

        if type == newton.JOINT_FREE or type == newton.JOINT_DISTANCE:
            t = wp.transform(
                wp.vec3(joint_q[q_start + 0], joint_q[q_start + 1], joint_q[q_start + 2]),
                wp.quat(joint_q[q_start + 3], joint_q[q_start + 4], joint_q[q_start + 5], joint_q[q_start + 6]),
            )

            v = wp.spatial_vector(
                wp.vec3(joint_qd[qd_start + 0], joint_qd[qd_start + 1], joint_qd[qd_start + 2]),
                wp.vec3(joint_qd[qd_start + 3], joint_qd[qd_start + 4], joint_qd[qd_start + 5]),
            )

            X_j = t
            v_j = v

        if type == newton.JOINT_D6 or type == newton.JOINT_COMPOUND or type == newton.JOINT_UNIVERSAL:
            pos = wp.vec3(0.0)
            rot = wp.quat_identity()
            vel_v = wp.vec3(0.0)
            vel_w = wp.vec3(0.0)

            for j in range(lin_axis_count):
                axis = joint_axis[axis_start + j]
                pos += axis * joint_q[q_start + j]
                vel_v += axis * joint_qd[qd_start + j]

            ia = axis_start + lin_axis_count
            iq = q_start + lin_axis_count
            iqd = qd_start + lin_axis_count
            for j in range(ang_axis_count):
                axis = joint_axis[ia + j]
                rot = rot * wp.quat_from_axis_angle(axis, joint_q[iq + j])
                vel_w += joint_qd[iqd + j] * axis

            X_j = wp.transform(pos, rot)
            v_j = wp.spatial_vector(vel_w, vel_v)

        # transform from world to joint anchor frame at child body
        X_wcj = X_wpj * X_j
        # transform from world to child body frame
        X_wc = X_wcj * wp.transform_inverse(X_cj)

        # transform velocity across the joint to world space
        angular_vel = wp.transform_vector(X_wpj, wp.spatial_top(v_j))
        linear_vel = wp.transform_vector(X_wpj, wp.spatial_bottom(v_j))

        v_wc = v_wpj + wp.spatial_vector(angular_vel, linear_vel)

        body_q[child] = X_wc
        body_qd[child] = v_wc


@wp.kernel
def eval_articulation_fk(
    articulation_start: wp.array(dtype=int),
    joint_q: wp.array(dtype=float),
    joint_qd: wp.array(dtype=float),
    joint_q_start: wp.array(dtype=int),
    joint_qd_start: wp.array(dtype=int),
    joint_type: wp.array(dtype=int),
    joint_parent: wp.array(dtype=int),
    joint_child: wp.array(dtype=int),
    joint_X_p: wp.array(dtype=wp.transform),
    joint_X_c: wp.array(dtype=wp.transform),
    joint_axis: wp.array(dtype=wp.vec3),
    joint_axis_start: wp.array(dtype=int),
    joint_axis_dim: wp.array(dtype=int, ndim=2),
    body_com: wp.array(dtype=wp.vec3),
    # outputs
    body_q: wp.array(dtype=wp.transform),
    body_qd: wp.array(dtype=wp.spatial_vector),
):
    tid = wp.tid()

    joint_start = articulation_start[tid]
    joint_end = articulation_start[tid + 1]

    eval_single_articulation_fk(
        joint_start,
        joint_end,
        joint_q,
        joint_qd,
        joint_q_start,
        joint_qd_start,
        joint_type,
        joint_parent,
        joint_child,
        joint_X_p,
        joint_X_c,
        joint_axis,
        joint_axis_start,
        joint_axis_dim,
        body_com,
        # outputs
        body_q,
        body_qd,
    )


@wp.kernel
def convert_body_xforms_to_warp_kernel(
    xpos: wp.array2d(dtype=wp.vec3),
    xquat: wp.array2d(dtype=wp.quat),
    to_mjc_body_index: wp.array(dtype=wp.int32),
    bodies_per_env: int,
    up_axis: int,
    # outputs
    body_q: wp.array(dtype=wp.transform),
):
    worldid, bodyid = wp.tid()
    wbi = bodies_per_env * worldid + bodyid
    mbi = to_mjc_body_index[bodyid]
    pos = xpos[worldid, mbi]
    quat = xquat[worldid, mbi]
    # convert from wxyz to xyzw
    quat = wp.quat(quat[1], quat[2], quat[3], quat[0])
    # quat = wp.quat(quat[3], quat[0], quat[1], quat[2])
    # quat = wp.quat_identity()
    # quat = wp.quat_inverse(quat)
    # rot_y2z = wp.quat_from_axis_angle(wp.vec3(1.0, 0.0, 0.0), wp.pi * 0.5)
    # quat = rot_y2z * quat
    if up_axis == 1:
        pos = wp.vec3(pos[0], pos[2], -pos[1])
        rot_y2z = wp.quat_from_axis_angle(wp.vec3(1.0, 0.0, 0.0), -wp.pi * 0.5)
        # pos = wp.quat_rotate(rot_y2z, pos)
        quat = rot_y2z * quat
    body_q[wbi] = wp.transform(pos, quat)


@wp.kernel
def update_body_mass_ipos_kernel(
    body_com: wp.array(dtype=wp.vec3f),
    body_mass: wp.array(dtype=float),
    bodies_per_env: int,
    up_axis: int,
    body_mapping: wp.array(dtype=int),
    # outputs
    body_ipos: wp.array2d(dtype=wp.vec3f),
    body_mass_out: wp.array2d(dtype=float),
):
    tid = wp.tid()
    worldid = wp.tid() // bodies_per_env
    index_in_env = wp.tid() % bodies_per_env
    mjc_idx = body_mapping[index_in_env]
    if mjc_idx == -1:
        return

    # Update COM position
    if up_axis == 1:
        body_ipos[worldid, mjc_idx] = wp.vec3f(body_com[tid][0], -body_com[tid][2], body_com[tid][1])
    else:
        body_ipos[worldid, mjc_idx] = body_com[tid]

    # Update mass
    body_mass_out[worldid, mjc_idx] = body_mass[tid]


@wp.kernel
def update_body_inertia_kernel(
    body_inertia: wp.array(dtype=wp.mat33f),
    body_quat: wp.array2d(dtype=wp.quatf),
    bodies_per_env: int,
    body_mapping: wp.array(dtype=int),
    up_axis: int,
    # outputs
    body_inertia_out: wp.array2d(dtype=wp.vec3f),
    body_iquat_out: wp.array2d(dtype=wp.quatf),
):
    tid = wp.tid()
    worldid = wp.tid() // bodies_per_env
    index_in_env = wp.tid() % bodies_per_env
    mjc_idx = body_mapping[index_in_env]
    if mjc_idx == -1:
        return

    # Get inertia tensor and body orientation
    I = body_inertia[tid]
    # body_q = body_quat[worldid, mjc_idx]

    # Calculate eigenvalues and eigenvectors
    eigenvectors, eigenvalues = wp.eig3(I)

    # Bubble sort for 3 elements in descending order
    for i in range(2):
        for j in range(2 - i):
            if eigenvalues[j] < eigenvalues[j + 1]:
                # Swap eigenvalues
                temp_val = eigenvalues[j]
                eigenvalues[j] = eigenvalues[j + 1]
                eigenvalues[j + 1] = temp_val
                # Swap eigenvectors
                temp_vec = eigenvectors[j]
                eigenvectors[j] = eigenvectors[j + 1]
                eigenvectors[j + 1] = temp_vec

    # this does not work yet, I think we are reporting in the wrong reference frame
    # Convert eigenvectors to quaternion (xyzw format for mujoco)
    # q = wp.quat_from_matrix(wp.mat33f(eigenvectors[0], eigenvectors[1], eigenvectors[2]))
    # q = wp.normalize(q)

    # if up_axis == 1:
    #     q_y2z = wp.static(wp.quat_from_axis_angle(wp.vec3(1.0, 0.0, 0.0), wp.pi * 0.5))
    #     q = q_y2z * q

    # Convert from wxyz to xyzw format and compose with body orientation
    # q = wp.quat(q[1], q[2], q[3], q[0])

    # Store results
    body_inertia_out[worldid, mjc_idx] = eigenvalues
    # body_iquat_out[worldid, mjc_idx] = q


@wp.kernel
def repeat_array_kernel(
    src: wp.array(dtype=Any),
    nelems_per_world: int,
    dst: wp.array(dtype=Any),
):
    tid = wp.tid()
    src_idx = tid % nelems_per_world
    dst[tid] = src[src_idx]


class MuJoCoSolver(SolverBase):
    """
    This solver provides an interface to simulate physics using the `MuJoCo <https://github.com/google-deepmind/mujoco>`_ physics engine,
    optimized with GPU acceleration through `mujoco_warp <https://github.com/google-deepmind/mujoco_warp>`_. It supports both MuJoCo and
    mujoco_warp backends, enabling efficient simulation of articulated systems with
    contacts and constraints.

    .. note::

        - This solver requires `mujoco_warp`_ and its dependencies to be installed.
        - For installation instructions, see the `mujoco_warp`_ repository.

    Example
    -------

    .. code-block:: python

        solver = newton.MuJoCoSolver(model)

        # simulation loop
        for i in range(100):
            solver.step(model, state_in, state_out, control, contacts, dt)
    """

    def __init__(
        self,
        model: Model,
        *,
        mjw_model: MjWarpModel | None = None,
        mjw_data: MjWarpData | None = None,
        separate_envs_to_worlds: bool | None = None,
        nefc_per_env: int = 100,
        iterations: int = 20,
        ls_iterations: int = 10,
        solver: int | str = "cg",
        integrator: int | str = "euler",
        use_mujoco: bool = False,
        disable_contacts: bool = False,
        register_collision_groups: bool = True,
        default_actuator_gear: float | None = None,
        actuator_gears: dict[str, float] | None = None,
        update_data_every: int = 1,
        save_to_mjcf: str | None = None,
    ):
        """
        Args:
            model (Model): the model to be simulated.
            mjw_model (MjWarpModel | None): Optional pre-existing MuJoCo Warp model. If provided with `mjw_data`, conversion from Newton model is skipped.
            mjw_data (MjWarpData | None): Optional pre-existing MuJoCo Warp data. If provided with `mjw_model`, conversion from Newton model is skipped.
            separate_envs_to_worlds (bool | None): If True, each Newton environment is mapped to a separate MuJoCo world. Defaults to `not use_mujoco`.
            nefc_per_env (int): Number of constraints per environment (world).
            iterations (int): Number of solver iterations.
            ls_iterations (int): Number of line search iterations for the solver.
            solver (int | str): Solver type. Can be "cg" or "newton", or their corresponding MuJoCo integer constants.
            integrator (int | str): Integrator type. Can be "euler", "rk4", or "implicit", or their corresponding MuJoCo integer constants.
            use_mujoco (bool): If True, use the pure MuJoCo backend instead of `mujoco_warp`.
            disable_contacts (bool): If True, disable contact computation in MuJoCo.
            register_collision_groups (bool): If True, register collision groups from the Newton model in MuJoCo.
            default_actuator_gear (float | None): Default gear ratio for all actuators. Can be overridden by `actuator_gears`.
            actuator_gears (dict[str, float] | None): Dictionary mapping joint names to specific gear ratios, overriding the `default_actuator_gear`.
            update_data_every (int): Frequency (in simulation steps) at which to update the MuJoCo Data object from the Newton state. If 0, Data is never updated after initialization.
            save_to_mjcf (str | None): Optional path to save the generated MJCF model file.

        """
        super().__init__(model)
        self.mujoco, self.mujoco_warp = import_mujoco()

        disableflags = 0
        if disable_contacts:
            disableflags |= self.mujoco.mjtDisableBit.mjDSBL_CONTACT
        if mjw_model is not None and mjw_data is not None:
            self.mjw_model = mjw_model
            self.mjw_data = mjw_data
            self.use_mujoco = False
        else:
            self.use_mujoco = use_mujoco
            if separate_envs_to_worlds is None:
                separate_envs_to_worlds = not use_mujoco
            self.convert_to_mjc(
                model,
                disableflags=disableflags,
                separate_envs_to_worlds=separate_envs_to_worlds,
                nefc_per_env=nefc_per_env,
                iterations=iterations,
                ls_iterations=ls_iterations,
                solver=solver,
                integrator=integrator,
                register_collision_groups=register_collision_groups,
                default_actuator_gear=default_actuator_gear,
                actuator_gears=actuator_gears,
                target_filename=save_to_mjcf,
            )
        self.update_data_every = update_data_every
        self._step = 0

    @override
    def step(self, model: Model, state_in: State, state_out: State, control: Control, contacts: Contact, dt: float):
        """
        Simulate the model for a given time step using the given control input.

        Args:
            model (Model): The model to simulate.
            state_in (State): The input state.
            state_out (State): The output state.
            dt (float): The time step (typically in seconds).
            control (Control): The control input. Defaults to `None` which means the control values from the :class:`Model` are used.
        """

        if self.use_mujoco:
            self.apply_mjc_control(self.model, state_in, control, self.mj_data)
            if self.update_data_every > 0 and self._step % self.update_data_every == 0:
                # XXX updating the mujoco state at every step may introduce numerical instability
                self.update_mjc_data(self.mj_data, model, state_in)
            self.mj_model.opt.timestep = dt
            self.mujoco.mj_step(self.mj_model, self.mj_data)
            self.update_newton_state(self.model, state_out, self.mj_data)
        else:
            self.apply_mjc_control(self.model, state_in, control, self.mjw_data)
            if self.update_data_every > 0 and self._step % self.update_data_every == 0:
                self.update_mjc_data(self.mjw_data, model, state_in)
            self.mjw_model.opt.timestep = dt
            with wp.ScopedDevice(self.model.device):
                self.mujoco_warp.step(self.mjw_model, self.mjw_data)
            self.update_newton_state(self.model, state_out, self.mjw_data)
        self._step += 1
        return state_out

    @override
    def notify_model_changed(self, flags: int):
        if flags & types.NOTIFY_FLAG_BODY_INERTIAL_PROPERTIES:
            self.update_model_inertial_properties()

    @staticmethod
    def _data_is_mjwarp(data):
        # Check if the data is a mujoco_warp Data object
        return hasattr(data, "nworld")

    @staticmethod
    def apply_mjc_control(model: Model, state: State, control: Control | None, mj_data: MjWarpData | MjData):
        if control is None or control.joint_f is None:
            return
        is_mjwarp = MuJoCoSolver._data_is_mjwarp(mj_data)
        if is_mjwarp:
            ctrl = mj_data.ctrl
            qfrc = mj_data.qfrc_applied
            nworld = mj_data.nworld
        else:
            ctrl = wp.empty((1, len(mj_data.ctrl)), dtype=wp.float32, device=model.device)
            qfrc = wp.empty((1, len(mj_data.qfrc_applied)), dtype=wp.float32, device=model.device)
            nworld = 1
        axes_per_env = model.joint_axis_count // nworld
        joints_per_env = model.joint_count // nworld
        bodies_per_env = model.body_count // nworld
        wp.launch(
            apply_mjc_control_kernel,
            dim=(nworld, axes_per_env),
            inputs=[
                control.joint_target,
                model.mjc_axis_to_actuator,  # pyright: ignore[reportAttributeAccessIssue]
                axes_per_env,
            ],
            outputs=[
                ctrl,
            ],
            device=model.device,
        )
        wp.launch(
            apply_mjc_qfrc_kernel,
            dim=(nworld, joints_per_env),
            inputs=[
                state.body_q,
                control.joint_f,
                model.joint_type,
                model.body_com,
                model.joint_child,
                model.joint_q_start,
                model.joint_qd_start,
                model.joint_axis_dim,
                joints_per_env,
                bodies_per_env,
            ],
            outputs=[
                qfrc,
            ],
            device=model.device,
        )
        if not is_mjwarp:
            mj_data.ctrl[:] = ctrl.numpy().flatten()
            mj_data.qfrc_applied[:] = qfrc.numpy()

    @staticmethod
    def update_mjc_data(mj_data: MjWarpData | MjData, model: Model, state: State | None = None):
        is_mjwarp = MuJoCoSolver._data_is_mjwarp(mj_data)
        if is_mjwarp:
            # we have a MjWarp Data object
            qpos = mj_data.qpos
            qvel = mj_data.qvel
            nworld = mj_data.nworld
        else:
            # we have a MjData object from Mujoco
            qpos = wp.empty((1, model.joint_coord_count), dtype=wp.float32, device=model.device)
            qvel = wp.empty((1, model.joint_dof_count), dtype=wp.float32, device=model.device)
            nworld = 1
        if state is None:
            joint_q = model.joint_q
            joint_qd = model.joint_qd
        else:
            joint_q = state.joint_q
            joint_qd = state.joint_qd
        joints_per_env = model.joint_count // nworld
        wp.launch(
            convert_warp_coords_to_mj_kernel,
            dim=(nworld, joints_per_env),
            inputs=[
                joint_q,
                joint_qd,
                joints_per_env,
                model.up_axis,
                model.joint_type,
                model.joint_q_start,
                model.joint_qd_start,
                model.joint_axis_dim,
            ],
            outputs=[qpos, qvel],
            device=model.device,
        )
        if not is_mjwarp:
            mj_data.qpos[:] = qpos.numpy().flatten()[: len(mj_data.qpos)]
            mj_data.qvel[:] = qvel.numpy().flatten()[: len(mj_data.qvel)]

    @staticmethod
    def update_newton_state(model: Model, state: State, mj_data: MjWarpData | MjData, eval_fk: bool = True):
        is_mjwarp = MuJoCoSolver._data_is_mjwarp(mj_data)
        if is_mjwarp:
            # we have a MjWarp Data object
            qpos = mj_data.qpos
            qvel = mj_data.qvel
            nworld = mj_data.nworld

            xpos = mj_data.xpos
            xquat = mj_data.xquat
        else:
            # we have a MjData object from Mujoco
            qpos = wp.array([mj_data.qpos], dtype=wp.float32, device=model.device)
            qvel = wp.array([mj_data.qvel], dtype=wp.float32, device=model.device)
            nworld = 1

            xpos = wp.array([mj_data.xpos], dtype=wp.vec3, device=model.device)
            xquat = wp.array([mj_data.xquat], dtype=wp.quat, device=model.device)
        joints_per_env = model.joint_count // nworld
        wp.launch(
            convert_mj_coords_to_warp_kernel,
            dim=(nworld, joints_per_env),
            inputs=[
                qpos,
                qvel,
                joints_per_env,
                int(model.up_axis),
                model.joint_type,
                model.joint_q_start,
                model.joint_qd_start,
                model.joint_axis_dim,
            ],
            outputs=[state.joint_q, state.joint_qd],
            device=model.device,
        )
        if eval_fk:
            # custom forward kinematics for handling multi-dof joints
            wp.launch(
                kernel=eval_articulation_fk,
                dim=model.articulation_count,
                inputs=[
                    model.articulation_start,
                    state.joint_q,
                    state.joint_qd,
                    model.joint_q_start,
                    model.joint_qd_start,
                    model.joint_type,
                    model.joint_parent,
                    model.joint_child,
                    model.joint_X_p,
                    model.joint_X_c,
                    model.joint_axis,
                    model.joint_axis_start,
                    model.joint_axis_dim,
                    model.body_com,
                ],
                outputs=[
                    state.body_q,
                    state.body_qd,
                ],
                device=model.device,
            )
        else:
            bodies_per_env = model.body_count // model.num_envs
            wp.launch(
                convert_body_xforms_to_warp_kernel,
                dim=(nworld, bodies_per_env),
                inputs=[
                    xpos,
                    xquat,
                    model.to_mjc_body_index,
                    bodies_per_env,
                    int(model.up_axis),
                ],
                outputs=[state.body_q],
                device=model.device,
            )

    def convert_to_mjc(
        self,
        model: Model,
        state: State | None = None,
        *,
        separate_envs_to_worlds: bool = True,
        iterations: int = 20,
        ls_iterations: int = 10,
        nefc_per_env: int = 100,  # number of constraints per world
        solver: int | str = "cg",
        integrator: int | str = "euler",
        disableflags: int = 0,
        impratio: float = 1.0,
        tolerance: float = 1e-8,
        ls_tolerance: float = 0.01,
        timestep: float = 0.01,
        cone: int = 0,
        register_collision_groups: bool = True,
        # maximum absolute joint limit value after which the joint is considered not limited
        joint_limit_threshold: float = 1e3,
        # these numbers come from the cartpole.xml model
        # joint_solref=(0.08, 1.0),
        # joint_solimp=(0.9, 0.95, 0.001, 0.5, 2.0),
        geom_solref: tuple[float, float] = (0.02, 1.0),
        geom_solimp: tuple[float, float, float, float, float] = (0.9, 0.95, 0.001, 0.5, 2.0),
        geom_friction: tuple[float, float, float] = (1.0, 0.05, 0.05),
        geom_condim: int = 3,
        target_filename: str | None = None,
        default_actuator_args: dict | None = None,
        default_actuator_gear: float | None = None,
        actuator_gears: dict[str, float] | None = None,
        actuated_axes: list[int] | None = None,
        skip_visual_only_geoms: bool = True,
        add_axes: bool = True,
    ) -> tuple[MjWarpModel, MjWarpData, MjModel, MjData]:
        """
        Convert a Newton model and state to MuJoCo (Warp) model and data.

        Args:
            Model (newton.Model): The Newton model to convert.
            State (newton.State): The Newton state to convert.

        Returns:
            tuple[MjWarpModel, MjWarpData, MjModel, MjData]: A tuple containing the model and data objects for ``mujoco_warp`` and MuJoCo.
        """
        mujoco, mujoco_warp = import_mujoco()

        actuator_args = {
            "ctrllimited": True,
            "ctrlrange": (-1.0, 1.0),
            "gear": [50.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "trntype": mujoco.mjtTrn.mjTRN_JOINT,
            # motor actuation properties (already the default settings in Mujoco)
            "gainprm": [1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "dyntype": mujoco.mjtDyn.mjDYN_NONE,
            "gaintype": mujoco.mjtGain.mjGAIN_FIXED,
            "biastype": mujoco.mjtBias.mjBIAS_NONE,
        }
        if default_actuator_args is not None:
            actuator_args.update(default_actuator_args)
        if default_actuator_gear is not None:
            actuator_args["gear"][0] = default_actuator_gear
        if actuator_gears is None:
            actuator_gears = {}

        if isinstance(solver, str):
            solver = {
                "cg": mujoco.mjtSolver.mjSOL_CG,
                "newton": mujoco.mjtSolver.mjSOL_NEWTON,
            }.get(solver.lower(), mujoco.mjtSolver.mjSOL_CG)

        if isinstance(integrator, str):
            integrator = {
                "euler": mujoco.mjtIntegrator.mjINT_EULER,
                "rk4": mujoco.mjtIntegrator.mjINT_RK4,
                "implicit": mujoco.mjtIntegrator.mjINT_IMPLICITFAST,
            }.get(integrator.lower(), mujoco.mjtIntegrator.mjINT_EULER)

        def quat2mjc(q):
            # convert from xyzw to wxyz
            return [q[3], q[0], q[1], q[2]]

        def pos2mjc(p):
            if model.up_axis == 1:
                # mujoco uses y-axis up, Warp uses z-axis up
                return [p[0], -p[2], p[1]]
            else:
                return p

        spec = mujoco.MjSpec()
        spec.option.disableflags = disableflags
        spec.option.gravity = pos2mjc(wp.vec3(*model.gravity))
        spec.option.timestep = timestep
        spec.option.solver = solver
        spec.option.integrator = integrator
        spec.option.iterations = iterations
        spec.option.ls_iterations = ls_iterations
        defaults = spec.default
        if callable(defaults):
            defaults = defaults()
        defaults.geom.condim = geom_condim
        defaults.geom.solref = geom_solref
        defaults.geom.solimp = geom_solimp
        defaults.geom.friction = geom_friction
        # defaults.geom.contype = 0
        spec.compiler.inertiafromgeom = mujoco.mjtInertiaFromGeom.mjINERTIAFROMGEOM_AUTO

        if add_axes:
            # add axes for debug visualization in MuJoCo viewer when loading the generated XML
            spec.worldbody.add_geom(
                type=mujoco.mjtGeom.mjGEOM_CYLINDER,
                name="axis_x",
                fromto=[0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                rgba=[1.0, 0.0, 0.0, 1.0],
                size=[0.01, 0.01, 0.01],
                contype=0,
                conaffinity=0,
            )
            spec.worldbody.add_geom(
                type=mujoco.mjtGeom.mjGEOM_CYLINDER,
                name="axis_y",
                fromto=[0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                rgba=[0.0, 1.0, 0.0, 1.0],
                size=[0.01, 0.01, 0.01],
                contype=0,
                conaffinity=0,
            )
            spec.worldbody.add_geom(
                type=mujoco.mjtGeom.mjGEOM_CYLINDER,
                name="axis_z",
                fromto=[0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
                rgba=[0.0, 0.0, 1.0, 1.0],
                size=[0.01, 0.01, 0.01],
                contype=0,
                conaffinity=0,
            )

        joint_parent = model.joint_parent.numpy().tolist()
        joint_child = model.joint_child.numpy().tolist()
        joint_parent_xform = model.joint_X_p.numpy()
        joint_child_xform = model.joint_X_c.numpy()
        joint_limit_lower = model.joint_limit_lower.numpy()
        joint_limit_upper = model.joint_limit_upper.numpy()
        joint_type = model.joint_type.numpy()
        joint_axis = model.joint_axis.numpy()
        joint_axis_start = model.joint_axis_start.numpy()
        joint_axis_dim = model.joint_axis_dim.numpy()
        joint_axis_mode = model.joint_axis_mode.numpy()
        joint_target_kd = model.joint_target_kd.numpy()
        joint_target_ke = model.joint_target_ke.numpy()
        joint_qd_start = model.joint_qd_start.numpy()
        joint_armature = model.joint_armature.numpy()
        body_q = model.body_q.numpy()
        body_mass = model.body_mass.numpy()
        body_inertia = model.body_inertia.numpy()
        body_com = model.body_com.numpy()
        shape_transform = model.shape_transform.numpy()
        shape_type = model.shape_geo.type.numpy()
        shape_size = model.shape_geo.scale.numpy()
        shape_collision_group = model.shape_collision_group
        num_collision_groups = int(np.max(shape_collision_group) + 1)

        # collision bitmask that corresponds to collision group -1 which collides with everything
        collision_mask_everything = 0
        for i in range(num_collision_groups + 1):
            collision_mask_everything |= 1 << i
        INT32_MAX = np.iinfo(np.int32).max
        if collision_mask_everything > INT32_MAX:
            wp.utils.warn(
                "Collision mask exceeds INT32_MAX while converting Newton model to MuJoCo, some collision groups will be ignored when using MuJoCo C."
            )
            collision_mask_everything = INT32_MAX

        # mapping from joint axis to actuator index
        axis_to_actuator = np.zeros((model.joint_axis_count,), dtype=np.int32) - 1
        actuator_count = 0

        # rotate Y axis to Z axis (used for correcting the alignment of capsules, cylinders)
        rot_y2z = wp.quat_from_axis_angle(wp.vec3(1.0, 0.0, 0.0), wp.pi * 0.5)
        rot_y2z_mat = np.array(wp.quat_to_matrix(rot_y2z)).reshape(3, 3)

        # supported non-fixed joint types in MuJoCo (fixed joints are handled by nesting bodies)
        supported_joint_types = {
            newton.JOINT_FREE,
            newton.JOINT_BALL,
            newton.JOINT_PRISMATIC,
            newton.JOINT_REVOLUTE,
            newton.JOINT_UNIVERSAL,
            newton.JOINT_COMPOUND,
            newton.JOINT_D6,
        }

        geom_type_mapping = {
            newton.GEO_SPHERE: mujoco.mjtGeom.mjGEOM_SPHERE,
            newton.GEO_PLANE: mujoco.mjtGeom.mjGEOM_PLANE,
            newton.GEO_CAPSULE: mujoco.mjtGeom.mjGEOM_CAPSULE,
            newton.GEO_CYLINDER: mujoco.mjtGeom.mjGEOM_CYLINDER,
            newton.GEO_BOX: mujoco.mjtGeom.mjGEOM_BOX,
            newton.GEO_MESH: mujoco.mjtGeom.mjGEOM_MESH,
        }
        geom_type_name = {
            newton.GEO_SPHERE: "sphere",
            newton.GEO_PLANE: "plane",
            newton.GEO_CAPSULE: "capsule",
            newton.GEO_CYLINDER: "cylinder",
            newton.GEO_BOX: "box",
            newton.GEO_MESH: "mesh",
        }

        mj_bodies = [spec.worldbody]
        # mapping from warp body id to mujoco body id
        body_mapping = {-1: 0}

        # ensure unique names
        body_names = {}
        joint_names = {}

        # only generate the first environment, replicate state of multiple worlds in MjData
        bodies_per_env = model.body_count
        shapes_per_env = model.shape_count
        joints_per_env = model.joint_count
        if separate_envs_to_worlds and model.num_envs > 0:
            bodies_per_env //= model.num_envs
            shapes_per_env //= model.num_envs
            joints_per_env //= model.num_envs

        # sort joints topologically depth-first since this is the order that will also be used
        # for placing bodies in the MuJoCo model
        joints_simple = list(zip(joint_parent, joint_child))
        joint_order = newton.utils.topological_sort(joints_simple[:joints_per_env], use_dfs=True)
        if any(joint_order != np.arange(joints_per_env)):
            wp.utils.warn(
                "Joint order is not in depth-first topological order while converting Newton model to MuJoCo, this may lead to diverging kinematics between MuJoCo and Newton."
            )

        # maps from body_id to transform to be applied to its children
        # i.e. its inverse child transform
        body_child_tf = {}

        def add_geoms(warp_body_id: int, perm_position: bool = False, incoming_xform: wp.transform | None = None):
            body = mj_bodies[body_mapping[warp_body_id]]
            shapes = model.body_shapes.get(warp_body_id)
            shape_flags = model.shape_flags.numpy()
            if not shapes:
                return
            for shape in shapes:
                if shape == model.shape_count - 1 and not model.ground:
                    # skip ground plane
                    continue
                elif skip_visual_only_geoms and not (shape_flags[shape] & int(newton.core.SHAPE_FLAG_COLLIDE_SHAPES)):
                    continue
                # elif separate_envs_to_worlds and shape >= shapes_per_env and shape != model.shape_count - 1:
                #     # this is a shape in a different environment, skip it
                #     # TODO fix handling of static shapes here, see cartpole.xml replication
                #     # that is missing the rail shapes
                #     continue
                stype = shape_type[shape]
                name = f"{geom_type_name[stype]}_{shape}"
                if stype == newton.GEO_PLANE and warp_body_id != -1:
                    raise ValueError("Planes can only be attached to static bodies")
                geom_params = {
                    "type": geom_type_mapping[stype],
                    "name": name,
                }
                if stype == newton.GEO_MESH:
                    mesh_src = model.shape_geo_src[shape]
                    spec.add_mesh(
                        name=name,
                        uservert=mesh_src.vertices.flatten(),
                        userface=mesh_src.indices.flatten(),
                    )
                    geom_params["meshname"] = name
                q = wp.quat(*shape_transform[shape, 3:])
                p = wp.vec3(*shape_transform[shape, :3])
                tf = wp.transform(p, q)
                if incoming_xform is not None:
                    # transform to world space
                    tf: wp.transform = incoming_xform * tf
                    q = tf.q
                    p = tf.p
                if stype in (newton.GEO_CAPSULE, newton.GEO_CYLINDER):
                    # mujoco aligns these shapes with the z-axis, Warp uses the y-axis
                    q = q * rot_y2z
                if model.up_axis == 2 and warp_body_id == -1:
                    # reverse rotation that aligned the z-axis with the y-axis
                    q = q * wp.quat_inverse(rot_y2z)
                if perm_position:
                    # mujoco aligns these shapes with the z-axis, Warp uses the y-axis
                    p = wp.vec3(p[0], -p[2], p[1])
                geom_params["pos"] = p
                geom_params["quat"] = quat2mjc(q)
                size = shape_size[shape]
                if np.any(size > 0.0):
                    # duplicate nonzero entries at places where size is 0
                    nonzero = size[size > 0.0][0]
                    size[size == 0.0] = nonzero
                    geom_params["size"] = size
                else:
                    # planes are always infinite for collision purposes in mujoco
                    geom_params["size"] = [5.0, 5.0, 5.0]
                if register_collision_groups:
                    # add contype, conaffinity for collision groups
                    if shape_collision_group[shape] == -1:
                        # this shape collides with everything
                        cmask = collision_mask_everything
                    else:
                        cmask = 1 << (shape_collision_group[shape] + 1)
                    if cmask <= INT32_MAX:
                        geom_params["contype"] = cmask
                        geom_params["conaffinity"] = cmask
                body.add_geom(**geom_params)

        # add static geoms attached to the worldbody
        add_geoms(-1, perm_position=model.up_axis == 1)

        # add joints, bodies and geoms
        for ji in joint_order:
            parent, child = joints_simple[ji]
            if child in body_mapping:
                raise ValueError(f"Body {child} already exists in the mapping")
            if child >= bodies_per_env:
                # this is a body in a different environment, skip it
                continue

            # add body
            body_mapping[child] = len(mj_bodies)
            parent_xform = joint_parent_xform[ji]
            tf_p = body_q[child, :3]
            tf_q = wp.quat(*body_q[child, 3:])
            joint_pos = wp.vec3(*joint_child_xform[ji, :3])
            if parent == -1:
                # reverse rotation that aligned the z-axis with the y-axis
                tf_q = wp.quat(*parent_xform[3:])
                if model.up_axis == 1:
                    tf_q = rot_y2z * tf_q
                tf_p = pos2mjc(tf_p)
            else:
                tf_p = parent_xform[:3]
                tf_q = wp.quat(*parent_xform[3:])

                incoming_xform = body_child_tf.get(parent)
                if incoming_xform is not None:
                    # apply the incoming transform from the parent body,
                    # which is the inverse of the parent joint's child transform
                    tf = incoming_xform * wp.transform(tf_p, tf_q)
                    tf_p = tf.p
                    tf_q = tf.q
                    joint_pos = wp.vec3(0.0, 0.0, 0.0)
            # ensure unique body name
            name = model.body_key[child]
            if name not in body_names:
                body_names[name] = 1
            else:
                while name in body_names:
                    body_names[name] += 1
                    name = f"{name}_{body_names[name]}"

            inertia = body_inertia[child]
            if model.up_axis == 1:
                inertia = rot_y2z_mat @ inertia @ rot_y2z_mat.T
            body = mj_bodies[body_mapping[parent]].add_body(
                name=name,
                pos=tf_p,
                quat=quat2mjc(tf_q),
                mass=body_mass[child],
                ipos=pos2mjc(body_com[child, :]),
                fullinertia=[inertia[0, 0], inertia[1, 1], inertia[2, 2], inertia[0, 1], inertia[0, 2], inertia[1, 2]],
                explicitinertial=True,
            )
            mj_bodies.append(body)

            # add joint
            j_type = joint_type[ji]
            axis_start = joint_axis_start[ji]
            qd_start = joint_qd_start[ji]
            name = model.joint_key[ji]
            if name not in joint_names:
                joint_names[name] = 1
            else:
                while name in joint_names:
                    joint_names[name] += 1
                    name = f"{name}_{joint_names[name]}"

            if j_type == newton.JOINT_FREE:
                body.add_joint(
                    name=name,
                    type=mujoco.mjtJoint.mjJNT_FREE,
                    damping=0.0,
                    limited=False,
                )
            elif j_type in supported_joint_types:
                lin_axis_count, ang_axis_count = joint_axis_dim[ji]
                # linear dofs
                for i in range(lin_axis_count):
                    ai = axis_start + i
                    axis = wp.vec3(*joint_axis[ai])
                    # reverse rotation of body to joint axis
                    # axis = wp.quat_rotate_inv(rot_correction2 * tf_q, axis)
                    # axis = wp.quat_rotate_inv(tf_q, axis)
                    joint_params = {
                        "armature": joint_armature[qd_start + i],
                        "pos": joint_pos,
                        # "quat": quat2mjc(joint_child_xform[ji, 3:]),
                    }
                    if joint_axis_mode[ai] == newton.JOINT_MODE_TARGET_POSITION:
                        joint_params["stiffness"] = joint_target_ke[ai]
                        joint_params["damping"] = joint_target_kd[ai]
                    lower, upper = joint_limit_lower[ai], joint_limit_upper[ai]
                    if lower == upper or (abs(lower) > joint_limit_threshold and abs(upper) > joint_limit_threshold):
                        joint_params["limited"] = False
                    else:
                        joint_params["limited"] = True
                        joint_params["range"] = (lower, upper)
                    axname = name
                    if lin_axis_count > 1 or ang_axis_count > 1:
                        axname += "_lin"
                    if lin_axis_count > 1:
                        axname += str(i)
                    body.add_joint(
                        name=axname,
                        type=mujoco.mjtJoint.mjJNT_SLIDE,
                        axis=axis,
                        **joint_params,
                    )
                    if actuated_axes is None or ai in actuated_axes:
                        # add actuator for this axis
                        gear = actuator_gears.get(axname)
                        if gear is not None:
                            args = {}
                            args.update(actuator_args)
                            args["gear"] = [gear, 0.0, 0.0, 0.0, 0.0, 0.0]
                        else:
                            args = actuator_args
                        spec.add_actuator(target=axname, **args)
                        axis_to_actuator[ai] = actuator_count
                        actuator_count += 1

                # angular dofs
                for i in range(lin_axis_count, lin_axis_count + ang_axis_count):
                    ai = axis_start + i
                    axis = wp.vec3(*joint_axis[ai])
                    # reverse rotation of body to joint axis
                    # axis = wp.quat_rotate_inv(rot_correction2 * tf_q, axis)
                    # axis = wp.quat_rotate_inv(tf_q, axis)
                    joint_params = {
                        "armature": joint_armature[qd_start + i],
                        "pos": joint_pos,
                        # "quat": quat2mjc(joint_child_xform[ji, 3:]),
                    }
                    if joint_axis_mode[ai] == newton.JOINT_MODE_TARGET_POSITION:
                        joint_params["stiffness"] = joint_target_ke[ai]
                        joint_params["damping"] = joint_target_kd[ai]
                    lower, upper = joint_limit_lower[ai], joint_limit_upper[ai]
                    if lower == upper or (abs(lower) > joint_limit_threshold and abs(upper) > joint_limit_threshold):
                        joint_params["limited"] = False
                    else:
                        joint_params["limited"] = True
                        joint_params["range"] = (np.rad2deg(lower), np.rad2deg(upper))
                    axname = name
                    if lin_axis_count > 1 or ang_axis_count > 1:
                        axname += "_ang"
                    if ang_axis_count > 1:
                        axname += str(i - lin_axis_count)
                    body.add_joint(
                        name=axname,
                        type=mujoco.mjtJoint.mjJNT_HINGE,
                        axis=axis,
                        **joint_params,
                    )
                    if actuated_axes is None or ai in actuated_axes:
                        # add actuator for this axis
                        gear = actuator_gears.get(axname)
                        if gear is not None:
                            args = {}
                            args.update(actuator_args)
                            args["gear"] = [gear, 0.0, 0.0, 0.0, 0.0, 0.0]
                        else:
                            args = actuator_args
                        spec.add_actuator(target=axname, **args)
                        axis_to_actuator[ai] = actuator_count
                        actuator_count += 1

            elif j_type != newton.JOINT_FIXED:
                raise NotImplementedError(f"Joint type {j_type} is not supported yet")

            # add geoms
            child_tf = wp.transform_inverse(wp.transform(*joint_child_xform[ji]))
            body_child_tf[child] = child_tf

            add_geoms(child, incoming_xform=child_tf)

        self.mj_model = spec.compile()

        if target_filename:
            import os

            with open(target_filename, "w") as f:
                f.write(spec.to_xml())
                print(f"Saved mujoco model to {os.path.abspath(target_filename)}")

        self.mj_data = mujoco.MjData(self.mj_model)
        self.mj_data.nefc = nefc_per_env

        self.mj_model.opt.tolerance = tolerance
        self.mj_model.opt.ls_tolerance = ls_tolerance
        self.mj_model.opt.cone = cone
        self.mj_model.opt.iterations = iterations
        self.mj_model.opt.ls_iterations = ls_iterations
        self.mj_model.opt.integrator = integrator
        self.mj_model.opt.solver = solver
        # m.opt.disableflags = disableflags
        self.mj_model.opt.impratio = impratio
        self.mj_model.opt.jacobian = mujoco.mjtJacobian.mjJAC_AUTO

        MuJoCoSolver.update_mjc_data(self.mj_data, model, state)

        # fill some MjWarp model fields that outdated after update_mjc_data.
        # just setting qpos0 to d.qpos leads to weird behavior here, needs
        # to be investigated.

        mujoco.mj_forward(self.mj_model, self.mj_data)

        with wp.ScopedDevice(model.device):
            # mapping from Newton joint axis index to MJC actuator index
            model.mjc_axis_to_actuator = wp.array(axis_to_actuator, dtype=wp.int32)  # pyright: ignore[reportAttributeAccessIssue]
            # mapping from MJC body index to Newton body index (skip world index -1)
            reverse_body_mapping = {v: k for k, v in body_mapping.items()}
            model.to_mjc_body_index = wp.array(  # pyright: ignore[reportAttributeAccessIssue]
                [reverse_body_mapping[i] + 1 for i in range(1, len(reverse_body_mapping))],
                dtype=wp.int32,
            )

            self.mjw_model = mujoco_warp.put_model(self.mj_model)
            if separate_envs_to_worlds:
                nworld = model.num_envs
            else:
                nworld = 1

            # expand model fields that can be expanded:
            self.expand_model_fields(self.mjw_model, nworld)

            # so far we have only defined the first environment,
            # now complete the data from the Newton model
            flags = types.NOTIFY_FLAG_BODY_INERTIAL_PROPERTIES
            self.notify_model_changed(flags)

            # TODO find better heuristics to determine nconmax and njmax
            nconmax = max(model.rigid_contact_max, self.mj_data.ncon * nworld)  # this avoids error in mujoco.
            njmax = max(nworld * nefc_per_env, nworld * self.mj_data.nefc)
            self.mjw_data = mujoco_warp.put_data(
                self.mj_model, self.mj_data, nworld=nworld, nconmax=nconmax, njmax=njmax
            )

    def expand_model_fields(self, mj_model: MjWarpModel, nworld: int):
        if nworld == 1:
            return

        model_fields_to_expand = [
            # "qpos0",
            # "qpos_spring",
            # "body_pos",
            # "body_quat",
            "body_ipos",
            # "body_iquat",
            "body_mass",
            # "body_subtreemass",
            # "subtree_mass",
            "body_inertia",
            # "body_invweight0",
            # "body_gravcomp",
            # "jnt_solref",
            # "jnt_solimp",
            # "jnt_pos",
            # "jnt_axis",
            # "jnt_stiffness",
            # "jnt_range",
            # "jnt_actfrcrange",
            # "jnt_margin",
            # "dof_armature",
            # "dof_damping",
            # "dof_invweight0",
            # "dof_frictionloss",
            # "dof_solimp",
            # "dof_solref",
            # "geom_matid",
            # "geom_solmix",
            # "geom_solref",
            # "geom_solimp",
            # "geom_size",
            # "geom_rbound",
            # "geom_pos",
            # "geom_quat",
            # "geom_friction",
            # "geom_margin",
            # "geom_gap",
            # "geom_rgba",
            # "site_pos",
            # "site_quat",
            # "cam_pos",
            # "cam_quat",
            # "cam_poscom0",
            # "cam_pos0",
            # "cam_mat0",
            # "light_pos",
            # "light_dir",
            # "light_poscom0",
            # "light_pos0",
            # "eq_solref",
            # "eq_solimp",
            # "eq_data",
            # "actuator_dynprm",
            # "actuator_gainprm",
            # "actuator_biasprm",
            # "actuator_ctrlrange",
            # "actuator_forcerange",
            # "actuator_actrange",
            # "actuator_gear",
            # "pair_solref",
            # "pair_solreffriction",
            # "pair_solimp",
            # "pair_margin",
            # "pair_gap",
            # "pair_friction",
            # "tendon_solref_lim",
            # "tendon_solimp_lim",
            # "tendon_range",
            # "tendon_margin",
            # "tendon_length0",
            # "tendon_invweight0",
            # "mat_rgba",
        ]

        def tile(x: wp.array):
            # Create new array with same shape but first dim multiplied by nworld
            new_shape = list(x.shape)
            new_shape[0] = nworld
            wp_array = {1: wp.array, 2: wp.array2d, 3: wp.array3d, 4: wp.array4d}[len(new_shape)]
            dst = wp_array(shape=new_shape, dtype=x.dtype, device=x.device)

            # Flatten arrays for kernel
            src_flat = x.flatten()
            dst_flat = dst.flatten()

            # Launch kernel to repeat data - one thread per destination element
            n_elems_per_world = dst_flat.shape[0] // nworld
            wp.launch(
                repeat_array_kernel, dim=dst_flat.shape[0], inputs=[src_flat, n_elems_per_world], outputs=[dst_flat]
            )
            return dst

        for field in mj_model.__dataclass_fields__:
            if field in model_fields_to_expand:
                array = getattr(mj_model, field)
                setattr(mj_model, field, tile(array))

    def update_model_inertial_properties(self):
        bodies_per_env = self.model.body_count // self.model.num_envs

        wp.launch(
            update_body_mass_ipos_kernel,
            dim=self.model.body_count,
            inputs=[
                self.model.body_com,
                self.model.body_mass,
                bodies_per_env,
                self.model.up_axis,
                self.model.to_mjc_body_index,
            ],
            outputs=[self.mjw_model.body_ipos, self.mjw_model.body_mass],
            device=self.model.device,
        )

        wp.launch(
            update_body_inertia_kernel,
            dim=self.model.body_count,
            inputs=[
                self.model.body_inertia,
                self.mjw_model.body_quat,
                bodies_per_env,
                self.model.to_mjc_body_index,
                self.model.up_axis,
            ],
            outputs=[self.mjw_model.body_inertia, self.mjw_model.body_iquat],
            device=self.model.device,
        )
