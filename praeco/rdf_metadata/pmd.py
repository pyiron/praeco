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
_OBO = "http://purl.obolibrary.org/obo/"

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

_PMDCO3_TEST_TYPE = URIRef(_PMD + "PMD_0000974")
# Only steel: the generic route to a material is a term labelled "porosity".
_PMDCO3_STEEL = URIRef(_PMD + "PMD_0020096")
_PMDCO3_TEST_METHOD = URIRef(_TTO + "TTO_0000054")
_PMDCO3_INPUT = URIRef(_OBO + "OBI_0000293")
_PMDCO3_REALIZES = URIRef(_OBO + "BFO_0000055")
_PMDCO3_DENOTES = URIRef(_OBO + "IAO_0000219")
_PMDCO3_VALUE_SPECIFICATION = URIRef(_OBO + "OBI_0001938")
_PMDCO3_HAS_VALUE = URIRef(_PMD + "PMD_0000006")

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


def _add_denoted_values(
    graph: Graph,
    values: dict[str, set[_Triple]],
    denoted: Node,
    path: tuple[_Triple, ...],
) -> None:
    """Record the values specified by the identifiers denoting a resource."""
    for identifier in graph.subjects(_PMDCO3_DENOTES, denoted):
        for specification in graph.objects(identifier, _PMDCO3_VALUE_SPECIFICATION):
            for value in graph.objects(specification, _PMDCO3_HAS_VALUE):
                _add_value(
                    values,
                    value,
                    (
                        *path,
                        (identifier, _PMDCO3_DENOTES, denoted),
                        (identifier, _PMDCO3_VALUE_SPECIFICATION, specification),
                        (specification, _PMDCO3_HAS_VALUE, value),
                    ),
                )


def _pmdco3_materials(graph: Graph) -> _Fact:
    values: dict[str, set[_Triple]] = {}
    for material in graph.subjects(RDF.type, _PMDCO3_STEEL):
        _add_denoted_values(
            graph, values, material, ((material, RDF.type, _PMDCO3_STEEL),)
        )
    return _Fact("pmdco3_material", values)


def _pmdco3_standards(graph: Graph, tests: Iterable[Node]) -> _Fact:
    values: dict[str, set[_Triple]] = {}
    for test in tests:
        for method in graph.objects(test, _PMDCO3_REALIZES):
            if (method, RDF.type, _PMDCO3_TEST_METHOD) in graph:
                _add_denoted_values(
                    graph,
                    values,
                    method,
                    (
                        (test, _PMDCO3_REALIZES, method),
                        (method, RDF.type, _PMDCO3_TEST_METHOD),
                    ),
                )
    return _Fact("pmdco3_test_standard", values)


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
    pmdco2 = _tests(graph, "pmdco2_tensile_test", _PMDCO2_TEST_TYPES, _PMDCO2_INPUT)
    pmdco3 = _tests(graph, "pmdco3_tensile_test", (_PMDCO3_TEST_TYPE,), _PMDCO3_INPUT)
    if not pmdco2.support and not pmdco3.support:
        return (), ()
    evidence = _evidence(pmdco2, pmdco3)
    diagnostics: list[Diagnostic] = []
    if pmdco2.support and pmdco3.support:
        diagnostics.append(
            Diagnostic(
                "pmd_generation_conflict",
                None,
                subject,
                "The file matches both the PMDco 2 and the PMDco 3 tensile-test "
                "patterns, so no PMD suggestions are offered.",
                False,
                evidence,
            )
        )
    if not sole_candidate:
        diagnostics.append(
            Diagnostic(
                "pmd_subject_not_sole_candidate",
                None,
                subject,
                "PMD tensile-test patterns summarize the whole file, so suggestions "
                "are offered only to its single eligible publication subject.",
                False,
                evidence,
            )
        )
    if diagnostics:
        return (), tuple(diagnostics)
    if pmdco2.support:
        materials = _pmdco2_materials(graph)
        standards = _pmdco2_standards(graph, pmdco2.support)
        return _compose(pmdco2, materials, standards, subject, context), ()
    materials = _pmdco3_materials(graph)
    standards = _pmdco3_standards(graph, pmdco3.support)
    return _compose(pmdco3, materials, standards, subject, context), ()
