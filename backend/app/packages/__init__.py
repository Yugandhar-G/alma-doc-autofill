"""Workflow packages — legal domains installed as data + graphs on the kernel.

Each package exports PACKAGE: WorkflowPackage from its package module and is
installed by adding it to app.registry.INSTALLED_PACKAGES. (The screener
still lives at app/screener for historical import stability; it exports the
same contract from app.screener.package.)
"""
