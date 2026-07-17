from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012


JSONPointer = Annotated[str, Field(pattern=r"^(?:/(?:[^~/]|~[01])*)*$")]
MemberName = Annotated[str, Field(min_length=1)]
PublicHttpUrl = Annotated[
    HttpUrl,
    WithJsonSchema(
        {
            "type": "string",
            "format": "uri",
            "pattern": r"^https?://",
        }
    ),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Provenance(StrictModel):
    method: Literal["synthetic-clean-room"]
    contains_customer_data: Literal[False]
    contains_production_logs: Literal[False]
    public_sources: list[PublicHttpUrl] = Field(min_length=1)

    @field_validator(
        "contains_customer_data", "contains_production_logs", mode="before"
    )
    @classmethod
    def require_literal_false(cls, value: Any) -> Any:
        if value is not False:
            raise ValueError("provenance privacy flags must be the boolean false")
        return value


class PackMetadata(StrictModel):
    name: str
    version: str
    license: str
    provenance: Provenance


class ReferenceIntegrityCheck(StrictModel):
    kind: Literal["reference_integrity"]
    code: str
    output_collection_pointer: JSONPointer
    output_reference_field: MemberName | None = None
    context_collection_pointer: JSONPointer
    context_id_field: MemberName | None = None


class UniqueByCheck(StrictModel):
    kind: Literal["unique_by"]
    code: str
    output_collection_pointer: JSONPointer
    field: MemberName | None = None


class ExactlyOneCheck(StrictModel):
    kind: Literal["exactly_one"]
    code: str
    output_object_pointer: JSONPointer
    fields: list[MemberName] = Field(min_length=2)

    @model_validator(mode="after")
    def require_distinct_fields(self) -> ExactlyOneCheck:
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("exactly_one fields must be distinct")
        return self


class SameLengthCheck(StrictModel):
    kind: Literal["same_length"]
    code: str
    output_collection_pointer: JSONPointer
    context_collection_pointer: JSONPointer


class CollectionProjectionEqualityCheck(StrictModel):
    kind: Literal["collection_projection_equality"]
    code: str
    output_collection_pointer: JSONPointer
    output_fields: list[MemberName] = Field(min_length=1)
    context_collection_pointer: JSONPointer
    context_fields: list[MemberName] = Field(min_length=1)

    @model_validator(mode="after")
    def require_matching_distinct_projections(
        self,
    ) -> CollectionProjectionEqualityCheck:
        if len(self.output_fields) != len(self.context_fields):
            raise ValueError("output_fields and context_fields must have equal length")
        if len(set(self.output_fields)) != len(self.output_fields):
            raise ValueError("output_fields must be distinct")
        if len(set(self.context_fields)) != len(self.context_fields):
            raise ValueError("context_fields must be distinct")
        return self


Check = Annotated[
    ReferenceIntegrityCheck
    | UniqueByCheck
    | ExactlyOneCheck
    | SameLengthCheck
    | CollectionProjectionEqualityCheck,
    Field(discriminator="kind"),
]


class Contract(StrictModel):
    output_schema: dict[str, Any]
    checks: list[Check] = Field(default_factory=list)


class ExpectedViolation(StrictModel):
    code: str
    path: JSONPointer


class Fixture(StrictModel):
    name: str
    note: str
    output: Any
    expected_valid: bool
    expected_violations: list[ExpectedViolation] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_consistent_expectation(self) -> Fixture:
        if self.expected_valid and self.expected_violations:
            raise ValueError("valid fixtures cannot expect violations")
        if not self.expected_valid and not self.expected_violations:
            raise ValueError("invalid fixtures must expect at least one violation")
        return self


class CaseDefinition(StrictModel):
    schema_version: Literal["1.0"]
    id: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
    category: Literal["structured-output", "tool-calls"]
    title: str
    summary: str
    failure_mode: str
    input: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    contract: Contract
    fixtures: list[Fixture] = Field(min_length=2)

    @model_validator(mode="after")
    def require_self_verifying_contract(self) -> CaseDefinition:
        dialect = self.contract.output_schema.get("$schema")
        if dialect not in (None, "https://json-schema.org/draft/2020-12/schema"):
            raise ValueError("output schemas must use JSON Schema Draft 2020-12")
        try:
            Draft202012Validator.check_schema(self.contract.output_schema)
        except SchemaError as error:
            raise ValueError(
                f"invalid Draft 2020-12 output schema: {error.message}"
            ) from error
        root = Resource.from_contents(
            self.contract.output_schema,
            default_specification=DRAFT202012,
        )
        registry = Registry().with_resource("", root).crawl()
        _validate_schema_references(root, registry.resolver_with_root(root))

        fixture_names = [fixture.name for fixture in self.fixtures]
        if len(set(fixture_names)) != len(fixture_names):
            raise ValueError("fixture names must be distinct within a case")
        if {fixture.expected_valid for fixture in self.fixtures} != {False, True}:
            raise ValueError(
                "each case must include both a valid and an invalid fixture"
            )

        check_codes = [check.code for check in self.contract.checks]
        if len(set(check_codes)) != len(check_codes):
            raise ValueError("relational check codes must be distinct within a case")
        if any(code.startswith("schema.") for code in check_codes):
            raise ValueError(
                "relational check codes cannot use the reserved schema.* namespace"
            )
        for check in self.contract.checks:
            if isinstance(check, ReferenceIntegrityCheck):
                context_items = _context_collection(
                    self.context,
                    check.context_collection_pointer,
                    check.code,
                )
                if check.context_id_field is not None and any(
                    not isinstance(item, dict) or check.context_id_field not in item
                    for item in context_items
                ):
                    raise ValueError(
                        f"relational check {check.code!r} context is missing "
                        f"field {check.context_id_field!r}"
                    )
            elif isinstance(check, SameLengthCheck):
                _context_collection(
                    self.context,
                    check.context_collection_pointer,
                    check.code,
                )
            elif isinstance(check, CollectionProjectionEqualityCheck):
                context_items = _context_collection(
                    self.context,
                    check.context_collection_pointer,
                    check.code,
                )
                if any(
                    not isinstance(item, dict)
                    or any(field not in item for field in check.context_fields)
                    for item in context_items
                ):
                    raise ValueError(
                        f"relational check {check.code!r} context is missing "
                        "a selected projection field"
                    )

        expected_codes = {
            violation.code
            for fixture in self.fixtures
            for violation in fixture.expected_violations
        }
        undeclared = {
            code
            for code in expected_codes
            if not code.startswith("schema.") and code not in check_codes
        }
        if undeclared:
            raise ValueError(
                f"fixtures expect undeclared error codes: {sorted(undeclared)}"
            )
        unexercised = set(check_codes) - expected_codes
        if unexercised:
            raise ValueError(
                f"relational checks lack a failing fixture: {sorted(unexercised)}"
            )
        return self


def _validate_schema_references(resource: Resource[Any], resolver: Any) -> None:
    contents = resource.contents
    if isinstance(contents, dict):
        for keyword in ("$ref", "$dynamicRef"):
            reference = contents.get(keyword)
            if not isinstance(reference, str):
                continue
            if not reference.startswith("#"):
                raise ValueError(f"output schema {keyword} must be a local fragment")
            try:
                resolver.lookup(reference)
            except Unresolvable as error:
                raise ValueError(
                    f"output schema {keyword} does not resolve: {reference}"
                ) from error

    for subresource in resource.subresources():
        _validate_schema_references(
            subresource,
            resolver.in_subresource(subresource),
        )


def _context_collection(context: Any, pointer: str, code: str) -> list[Any]:
    current = context
    if pointer:
        for token in pointer[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
                continue
            if (
                isinstance(current, list)
                # `0` is the canonical JSON Pointer array index, not a credential.
                and re.fullmatch(r"0|[1-9][0-9]*", token)
                and int(token) < len(current)
            ):
                current = current[int(token)]
                continue
            else:
                raise ValueError(
                    f"relational check {code!r} context pointer does not resolve: "
                    f"{pointer}"
                )
    if not isinstance(current, list):
        raise ValueError(
            f"relational check {code!r} context pointer must select an array: {pointer}"
        )
    return current


class CasePack(StrictModel):
    pack: PackMetadata
    cases: list[CaseDefinition] = Field(min_length=1)


class Violation(StrictModel):
    code: str
    path: str
    message: str
