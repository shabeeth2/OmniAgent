"""Bounded, read-only presentation catalog. No executable UI or action dispatch."""
import json
import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from langchain.tools import tool

CATALOG_ID = 'urn:agent-tool-scale:read-only:v1'
SafeText = Annotated[str, StringConstraints(max_length=2000, pattern=r'^[^<>]*$')]
Identifier = Annotated[str, StringConstraints(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, strict=True)


class Layout(StrictModel):
    id: Identifier
    component: Literal['Row', 'Column']
    children: list[Identifier] = Field(min_length=1, max_length=49)


class Text(StrictModel):
    id: Identifier
    component: Literal['Text']
    text: SafeText


class Metric(StrictModel):
    id: Identifier
    component: Literal['Metric']
    label: SafeText
    value: SafeText


class Table(StrictModel):
    id: Identifier
    component: Literal['Table']
    columns: list[SafeText] = Field(min_length=1, max_length=12)
    rows: list[list[SafeText | float]] = Field(max_length=200)

    @model_validator(mode='after')
    def rectangular(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError('Every row must match the columns')
        return self


class Point(StrictModel):
    label: SafeText
    value: float


class Chart(StrictModel):
    id: Identifier
    component: Literal['BarChart', 'LineChart']
    title: SafeText
    unit: SafeText
    points: list[Point] = Field(min_length=1, max_length=200)


Component = Annotated[Layout | Text | Metric | Table | Chart, Field(discriminator='component')]


class Presentation(StrictModel):
    title: SafeText
    source: SafeText
    incomplete: bool = False
    components: list[Component] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def safe_tree(self):
        encoded = json.dumps(self.model_dump())
        if len(encoded.encode()) > 128_000:
            raise ValueError('Surface exceeds 128 KB')
        if re.search(r'(?:https?:|javascript:|data:|file:|ftp:|www\.|//)', encoded, re.I):
            raise ValueError('Resource URLs and executable content are not supported')
        nodes = {node.id: node for node in self.components}
        if len(nodes) != len(self.components) or 'root' not in nodes:
            raise ValueError('Unique component IDs and a root component are required')
        seen = set()

        def visit(key):
            if key not in nodes or key in seen:
                raise ValueError('Components must form a tree without cycles or missing references')
            seen.add(key)
            for child in getattr(nodes[key], 'children', []):
                visit(child)

        visit('root')
        if seen != nodes.keys():
            raise ValueError('Every component must be reachable from root')
        return self


def build_surface(presentation: Presentation, surface_id: str) -> dict:
    return {
        'id': surface_id, 'title': presentation.title, 'source': presentation.source,
        'incomplete': presentation.incomplete,
        'messages': [
            {'version': 'v0.9', 'createSurface': {'surfaceId': surface_id, 'catalogId': CATALOG_ID}},
            {'version': 'v0.9', 'updateComponents': {'surfaceId': surface_id,
                'components': [node.model_dump() for node in presentation.components]}},
        ],
    }


@tool(args_schema=Presentation)
def present_ui(**kwargs) -> str:
    """Present read-only charts, tables or metrics. Supply a tree rooted at root, source label and separate currency units. Call alone. Maximum four surfaces per response; no actions or URLs."""
    return 'Presentation recorded.'
