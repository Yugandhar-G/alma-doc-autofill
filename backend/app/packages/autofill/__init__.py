"""Autofill workflow package: extraction → human review (interrupt) →
guardrailed population with read-back diff — the original product surface,
now a checkpointed graph on the kernel runtime. Extraction itself runs at
the HTTP boundary (fast guardrail feedback, no document bytes in graph
state); the graph owns everything from review onward, which is what makes a
run resumable across a restart mid-review.
"""
