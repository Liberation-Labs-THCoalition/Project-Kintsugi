"""Domain-specific ontology extensions for Kintsugi.

Each domain module provides a factory function that returns an OntologyKernel
populated with domain-specific concepts, constraints, relations, and workflows.
Register into a parent kernel via kernel.register_domain(name, extension).
"""
