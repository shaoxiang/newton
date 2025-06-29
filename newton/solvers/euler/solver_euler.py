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

from newton.core.types import override
from newton.sim import Contacts, Control, Model, State

from ..solver import SolverBase
from .kernels import (
    eval_bending_forces,
    eval_body_contact_forces,
    eval_body_joint_forces,
    eval_muscle_forces,
    eval_particle_body_contact_forces,
    eval_spring_forces,
    eval_tetrahedral_forces,
    eval_triangle_contact_forces,
    eval_triangle_forces,
)
from .particles import eval_particle_forces


class SemiImplicitSolver(SolverBase):
    """A semi-implicit integrator using symplectic Euler

    After constructing `Model` and `State` objects this time-integrator
    may be used to advance the simulation state forward in time.

    Semi-implicit time integration is a variational integrator that
    preserves energy, however it not unconditionally stable, and requires a time-step
    small enough to support the required stiffness and damping forces.

    See: https://en.wikipedia.org/wiki/Semi-implicit_Euler_method

    Example
    -------

    .. code-block:: python

        solver = newton.solvers.SemiImplicitSolver(model)

        # simulation loop
        for i in range(100):
            solver.step(model, state_in, state_out, control, contacts, dt)
            state_in, state_out = state_out, state_in

    """

    def __init__(
        self,
        model: Model,
        angular_damping: float = 0.05,
        friction_smoothing: float = 1.0,
        joint_attach_ke: float = 1.0e4,
        joint_attach_kd: float = 1.0e2,
    ):
        """Create a new Euler solver.

        Args:
            model (Model): Model to use by this solver.
            angular_damping (float, optional): Angular damping factor to be used in rigid body integration. Defaults to 0.05.
            friction_smoothing (float, optional): Huber norm delta used for friction velocity normalization (see :func:`warp.math.norm_huber`). Defaults to 1.0.
            joint_attach_ke (float, optional): Joint attachment spring stiffness. Defaults to 1.0e4.
            joint_attach_kd (float, optional): Joint attachment spring damping. Defaults to 1.0e2.
        """
        super().__init__(model=model)
        self.angular_damping = angular_damping
        self.friction_smoothing = friction_smoothing
        self.joint_attach_ke = joint_attach_ke
        self.joint_attach_kd = joint_attach_kd

    @override
    def step(
        self,
        model: Model,
        state_in: State,
        state_out: State,
        control: Control,
        contacts: Contacts,
        dt: float,
    ):
        with wp.ScopedTimer("simulate", False):
            particle_f = None
            body_f = None

            if state_in.particle_count:
                particle_f = state_in.particle_f

            if state_in.body_count:
                body_f = state_in.body_f

            if control is None:
                control = model.control(clone_variables=False)

            # damped springs
            eval_spring_forces(model, state_in, particle_f)

            # triangle elastic and lift/drag forces
            eval_triangle_forces(model, state_in, control, particle_f)

            # triangle/triangle contacts
            eval_triangle_contact_forces(model, state_in, particle_f)

            # triangle bending
            eval_bending_forces(model, state_in, particle_f)

            # tetrahedral FEM
            eval_tetrahedral_forces(model, state_in, control, particle_f)

            # body joints
            eval_body_joint_forces(model, state_in, control, body_f, self.joint_attach_ke, self.joint_attach_kd)

            # particle-particle interactions
            eval_particle_forces(model, state_in, particle_f)

            # body contacts
            eval_body_contact_forces(model, state_in, contacts, friction_smoothing=self.friction_smoothing)

            # particle shape contact
            eval_particle_body_contact_forces(
                model, state_in, contacts, particle_f, body_f, body_f_in_world_frame=False
            )

            # muscles
            if False:
                eval_muscle_forces(model, state_in, control, body_f)

            self.integrate_bodies(model, state_in, state_out, dt, self.angular_damping)

            self.integrate_particles(model, state_in, state_out, dt)

            return state_out
