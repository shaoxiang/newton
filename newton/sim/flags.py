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

"""Implementation of the Newton model class."""

import warp as wp

# model update flags - used for solver.notify_model_update()

NOTIFY_FLAG_JOINT_PROPERTIES = wp.constant(1 << 0)
"""Indicates joint property updates: joint_q, joint_X_p, joint_X_c."""

NOTIFY_FLAG_JOINT_AXIS_PROPERTIES = wp.constant(1 << 1)
"""Indicates joint axis property updates: joint_target, joint_target_ke, joint_target_kd, joint_dof_mode, joint_limit_upper, joint_limit_lower, joint_limit_ke, joint_limit_kd."""

NOTIFY_FLAG_DOF_PROPERTIES = wp.constant(1 << 2)
"""Indicates degree-of-freedom property updates: joint_qd, joint_f, joint_armature."""

NOTIFY_FLAG_BODY_PROPERTIES = wp.constant(1 << 3)
"""Indicates body property updates: body_q, body_qd."""

NOTIFY_FLAG_BODY_INERTIAL_PROPERTIES = wp.constant(1 << 4)
"""Indicates body inertial property updates: body_com, body_inertia, body_inv_inertia, body_mass, body_inv_mass."""

NOTIFY_FLAG_SHAPE_PROPERTIES = wp.constant(1 << 5)
"""Indicates shape property updates: shape_transform, shape_geo."""


__all__ = [
    "NOTIFY_FLAG_BODY_INERTIAL_PROPERTIES",
    "NOTIFY_FLAG_BODY_PROPERTIES",
    "NOTIFY_FLAG_DOF_PROPERTIES",
    "NOTIFY_FLAG_JOINT_AXIS_PROPERTIES",
    "NOTIFY_FLAG_JOINT_PROPERTIES",
    "NOTIFY_FLAG_SHAPE_PROPERTIES",
]
