"""Exact PMD tensile-test patterns and the suggestions they support.

Rules match exact IRIs and paths: no inference, import loading, or decisions from
labels, namespaces, or instance identifiers. A rule's name is its evidence's name.
The file's tests are not linked to its publication subject, so a suggestion
summarizes the whole file and is offered only to the sole eligible subject.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, NamedTuple

from rdflib import RDF, BNode, Graph, Literal, URIRef
from rdflib.term import Node

from praeco.rdf_metadata.models import Diagnostic, Evidence, Suggestion

_PMD = "https://w3id.org/pmd/co/"
_TTO = "https://w3id.org/pmd/tto/"

# Each pair lists the declared IRI, then the undeclared one used by real data.
_PMDCO2_TEST_TYPES = (URIRef(_TTO + "TensileTest"), URIRef(_PMD + "TensileTest"))
_PMDCO2_MATERIAL_TYPES = (
    URIRef(_PMD + "MaterialDesignation"),
    URIRef(_PMD + "materialDesignation"),
)
_PMDCO2_NORM = URIRef(_PMD + "Norm")
_PMDCO2_INPUT = URIRef(_PMD + "input")
_PMDCO2_CHARACTERISTIC = URIRef(_PMD + "characteristic")
_PMDCO2_VALUE = URIRef(_PMD + "value")

_Triple = tuple[Node, Node, Node]


class _Fact(NamedTuple):
    """A rule's result: each distinct test or value with its supporting triples."""

    rule: str
    support: Mapping[Any, set[_Triple]]


def _add_value(
    values: dict[str, set[_Triple]], term: Node, triples: Iterable[_Triple]
) -> None:
    """Record a non-blank literal; any other term is not a fact."""
    if isinstance(term, Literal) and str(term).strip():
        values.setdefault(str(term).strip(), set()).update(triples)


def _tests(
    graph: Graph, rule: str, types: tuple[URIRef, ...], input_predicate: URIRef
) -> _Fact:
    """Find typed resources with a specified input, which excludes sub-steps."""
    tests: dict[Node, set[_Triple]] = {}
    for rdf_type in types:
        for test in graph.subjects(RDF.type, rdf_type):
            inputs = [
                (test, input_predicate, item)
                for item in graph.objects(test, input_predicate)
            ]
            if inputs:
                tests.setdefault(test, set()).update(
                    (*inputs, (test, RDF.type, rdf_type))
                )
    return _Fact(rule, tests)


def _pmdco2_materials(graph: Graph) -> _Fact:
    values: dict[str, set[_Triple]] = {}
    for rdf_type in _PMDCO2_MATERIAL_TYPES:
        for item in graph.subjects(RDF.type, rdf_type):
            for value in graph.objects(item, _PMDCO2_VALUE):
                _add_value(
                    values,
                    value,
                    ((item, RDF.type, rdf_type), (item, _PMDCO2_VALUE, value)),
                )
    return _Fact("pmdco2_material", values)


def _pmdco2_standards(graph: Graph, tests: Iterable[Node]) -> _Fact:
    values: dict[str, set[_Triple]] = {}
    for test in tests:
        for item in graph.objects(test, _PMDCO2_CHARACTERISTIC):
            if (item, RDF.type, _PMDCO2_NORM) not in graph:
                continue
            for value in graph.objects(item, _PMDCO2_VALUE):
                _add_value(
                    values,
                    value,
                    (
                        (test, _PMDCO2_CHARACTERISTIC, item),
                        (item, RDF.type, _PMDCO2_NORM),
                        (item, _PMDCO2_VALUE, value),
                    ),
                )
    return _Fact("pmdco2_test_standard", values)


def _evidence(*facts: _Fact) -> tuple[Evidence, ...]:
    """Give one entry per applied rule, in the given order, with sorted triples."""
    return tuple(
        Evidence(
            fact.rule,
            tuple(
                sorted(
                    {
                        (s.n3(), p.n3(), o.n3())
                        for triples in fact.support.values()
                        for s, p, o in triples
                    }
                )
            ),
        )
        for fact in facts
        if fact.support
    )


def _ordered(values: Iterable[str]) -> list[str]:
    return sorted(values, key=lambda value: (value.casefold(), value))


def _listing(label: str, values: Iterable[str]) -> str:
    ordered = _ordered(values)
    return f"{label}{'' if len(ordered) == 1 else 's'}: {', '.join(ordered)}."


def _compose(
    tests: _Fact,
    materials: _Fact,
    standards: _Fact,
    subject: URIRef | BNode,
    context: object,
) -> tuple[Suggestion[object], ...]:
    """State only what the rules found; absent facts drop their sentences."""
    count = len(tests.support)
    sentences = [f"Data from {count} tensile test{'' if count == 1 else 's'}."]
    if materials.support:
        sentences.append(_listing("Material", materials.support))
    if standards.support:
        sentences.append(_listing("Test standard", standards.support))
    return (
        Suggestion(
            "description",
            " ".join(sentences),
            _evidence(tests, materials, standards),
            context,
            subject,
        ),
        Suggestion(
            "keywords",
            tuple(_ordered({*materials.support, "tensile test"})),
            _evidence(tests, materials),
            context,
            subject,
        ),
    )


def derive_pmd_suggestions(
    graph: Graph, subject: URIRef | BNode, sole_candidate: bool, context: object
) -> tuple[tuple[Suggestion[object], ...], tuple[Diagnostic, ...]]:
    """Return suggestions for a matching signature, or why none are offered.

    Without a signature there is neither a suggestion nor a diagnostic.
    """
    tests = _tests(graph, "pmdco2_tensile_test", _PMDCO2_TEST_TYPES, _PMDCO2_INPUT)
    if not tests.support:
        return (), ()
    if not sole_candidate:
        return (), (
            Diagnostic(
                "pmd_subject_not_sole_candidate",
                None,
                subject,
                "PMD tensile-test patterns summarize the whole file, so suggestions "
                "are offered only to its single eligible publication subject.",
                False,
                _evidence(tests),
            ),
        )
    materials = _pmdco2_materials(graph)
    standards = _pmdco2_standards(graph, tests.support)
    return _compose(tests, materials, standards, subject, context), ()
