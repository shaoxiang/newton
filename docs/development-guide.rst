Development Guide
=================

This document is a guide for developers who want to contribute to the project or understand its internal workings in more detail.

Environment setup
-----------------

Clone the repository
^^^^^^^^^^^^^^^^^^^^

.. code-block:: console

    git clone git@github.com:newton-physics/newton.git
    cd newton

Using uv
^^^^^^^^

`uv <https://docs.astral.sh/uv/>`_ is a Python package and project manager.

Install uv:

.. tab-set::
    :sync-group: os

    .. tab-item:: macOS / Linux
        :sync: linux

        .. code-block:: console

            curl -LsSf https://astral.sh/uv/install.sh | sh

    .. tab-item:: Windows
        :sync: windows

        .. code-block:: console

            powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

Run basic examples:

.. code-block:: console

    # An example with basic dependencies
    uv run newton/examples/example_quadruped.py

    # An example that requires extras
    uv run --all-extras newton/examples/example_humanoid.py

When using uv, the `lockfile <https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile>`__
(``uv.lock``) is used to resolve project dependencies
into exact versions for reproducibility among different machines.

Sometimes, a dependency in the lockfile needs to be updated to a newer version.
This can be done by running ``uv lock --upgrade-package <package-name>``:

.. code-block:: console

    uv lock --upgrade-package warp-lang

    uv lock --upgrade-package mujoco-warp

uv also provides a command to update all dependencies in the lockfile:

.. code-block:: console

    uv lock -U

Remember to commit ``uv.lock`` after running a command that updates the lockfile.

Using venv
^^^^^^^^^^

These instructions are meant for users who wish to set up a development environment using `venv <https://docs.python.org/3/library/venv.html>`__
or Conda (e.g. from `Miniforge <https://github.com/conda-forge/miniforge>`__).

.. tab-set::
    :sync-group: os

    .. tab-item:: macOS / Linux
        :sync: linux

        .. code-block:: console

            python -m venv .venv
            source .venv/bin/activate

    .. tab-item:: Windows (console)
        :sync: windows

        .. code-block:: console

            python -m venv .venv
            .venv\Scripts\activate.bat

    .. tab-item:: Windows (PowerShell)
        :sync: windows-ps

        .. code-block:: console

            python -m venv .venv
            .venv\Scripts\Activate.ps1

Installing dependencies including optional ones:

.. code-block:: console

    python -m pip install mujoco --pre -f https://py.mujoco.org/
    python -m pip install warp-lang --pre -U -f https://pypi.nvidia.com/warp-lang/
    python -m pip install git+https://github.com/google-deepmind/mujoco_warp.git@main
    python -m pip install -e .[dev]

Run basic examples:

.. code-block:: console

    # An example with basic dependencies
    python newton/examples/example_quadruped.py

    # An example that requires extras
    python newton/examples/example_humanoid.py

Running the tests
-----------------

The Newton test suite supports both ``uv`` and standard ``venv`` workflows,
and by default runs in up to eight parallel processes. On some systems, the
tests must be run in a serial manner with ``--serial-fallback`` due to an
outstanding bug.

Some tests rely on optional dependencies (like `usd-core <https://pypi.org/project/usd-core/>`__) and will be skipped if not installed.  
Pass ``--help`` to either runner to see all available flags.

.. tab-set::
    :sync-group: env

    .. tab-item:: uv
        :sync: uv
        
        .. code-block:: console

            # install all extras and run tests
            uv run --all-extras -m newton.tests

    .. tab-item:: venv
        :sync: venv

        .. code-block:: console

            # install dev extras (including testing & coverage deps)
            python -m pip install -e .[dev]
            # run tests
            python -m newton.tests

To generate a coverage report:

.. tab-set::
    :sync-group: env

    .. tab-item:: uv
        :sync: uv

        .. code-block:: console
            
            # append the coverage flags:
            uv run --all-extras -m newton.tests --coverage --coverage-html htmlcov

    .. tab-item:: venv
        :sync: venv

        .. code-block:: console

            # append the coverage flags and make sure `coverage[toml]` is installed (it comes in `[dev]`)
            python -m newton.tests --coverage --coverage-html htmlcov

The file ``htmlcov/index.html`` can be opened with a web browser to view the coverage report.

Code formatting and linting
---------------------------

`Ruff <https://docs.astral.sh/ruff/>`_ is used for Python linting and code formatting.
`pre-commit <https://pre-commit.com/>`_ can be used to ensure that local code complies with Newton's checks.
From the top of the repository, run:

.. tab-set::
    :sync-group: env

    .. tab-item:: uv
        :sync: uv

        .. code-block:: console

            uvx pre-commit run -a

    .. tab-item:: venv
        :sync: venv

        .. code:: console

            python -m pip install pre-commit
            pre-commit run -a

To automatically run pre-commit hooks with ``git commit``:

.. tab-set::
    :sync-group: env

    .. tab-item:: uv
        :sync: uv

        .. code-block:: console

            uvx pre-commit install

    .. tab-item:: venv
        :sync: venv

        .. code:: console

            pre-commit install

The hooks can be uninstalled with ``pre-commit uninstall``.

Building the documentation
--------------------------

To build the documentation locally, ensure you have the documentation dependencies installed.

.. tab-set::
    :sync-group: env

    .. tab-item:: uv
        :sync: uv

        .. code-block:: console

            rm -rf docs/_build
            uv run --extra docs sphinx-build -W -b html docs docs/_build/html

    .. tab-item:: venv
        :sync: venv

        .. code:: console

            python -m pip install -e .[docs]
            cd path/to/newton/docs && make html

The built documentation will be available in ``docs/_build/html``.

Testing documentation code snippets
-----------------------------------

The ``doctest`` Sphinx builder is used to ensure that code snippets in the documentation remain up-to-date.

The doctests can be run with:

.. tab-set::
    :sync-group: env

    .. tab-item:: uv
        :sync: uv

        .. code-block:: console

            uv run --extra docs sphinx-build -W -b doctest docs docs/_build/doctest

    .. tab-item:: venv
        :sync: venv

        .. code:: console

            python -m sphinx -W -b doctest docs docs/_build/doctest

For more information, see the `sphinx.ext.doctest <https://www.sphinx-doc.org/en/master/usage/extensions/doctest.html>`__
documentation.

Style Guide
-----------
- Follow PEP 8 for Python code.
- Use Google-style docstrings (compatible with Napoleon extension).
- Write clear, concise commit messages.
- Keep pull requests focused on a single feature or bug fix.

Roadmap and Future Work
-----------------------

(Placeholder for future roadmap and planned features)

- Advanced solver coupling
- More comprehensive sensor models
- Expanded robotics examples

See the `GitHub Discussions <https://github.com/newton-physics/newton/discussions>`__ for ongoing feature planning.

Contribution Guide
==================

Some ways to contribute to the development of Newton include:

* Reporting bugs and requesting new features on `GitHub <https://github.com/newton-physics/newton/issues>`__.
* Asking questions, sharing your work, or participating in discussion threads on
  `GitHub <https://github.com/newton-physics/newton/discussions>`__.
* Adding new examples to the Newton repository.
* Documentation improvements.
* Contributing bug fixes or new features.

Code contributions
------------------

Code contributions from the community are welcome.
Rather than requiring a formal Contributor License Agreement (CLA), we use the
`Developer Certificate of Origin <https://developercertificate.org/>`__ to
ensure contributors have the right to submit their contributions to this project.
Please ensure that all commits have a
`sign-off <https://git-scm.com/docs/git-commit#Documentation/git-commit.txt--s>`__ 
added with an email address that matches the commit author
to agree to the DCO terms for each particular contribution.

The full text of the DCO is as follows:

.. code-block:: text

    Version 1.1

    Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

    Everyone is permitted to copy and distribute verbatim copies of this
    license document, but changing it is not allowed.


    Developer's Certificate of Origin 1.1

    By making a contribution to this project, I certify that:

    (a) The contribution was created in whole or in part by me and I
        have the right to submit it under the open source license
        indicated in the file; or

    (b) The contribution is based upon previous work that, to the best
        of my knowledge, is covered under an appropriate open source
        license and I have the right under that license to submit that
        work with modifications, whether created in whole or in part
        by me, under the same open source license (unless I am
        permitted to submit under a different license), as indicated
        in the file; or

    (c) The contribution was provided directly to me by some other
        person who certified (a), (b) or (c) and I have not modified
        it.

    (d) I understand and agree that this project and the contribution
        are public and that a record of the contribution (including all
        personal information I submit with it, including my sign-off) is
        maintained indefinitely and may be redistributed consistent with
        this project or the open source license(s) involved.

Contributors are encouraged to first open an issue on GitHub to discuss proposed
feature contributions and gauge potential interest.
