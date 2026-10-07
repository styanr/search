from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class Action:
    label: str
    kind: str
    payload: object
    filename: str = ""


@dataclass(kw_only=True)
class Card:
    kind: ClassVar[str] = "card"
    priority: ClassVar[int] = 9
    anchored: ClassVar[bool] = False
    accent: ClassVar[str] = "neutral"

    title: str
    source: str = ""
    url: str = ""
    actions: list[Action] = field(default_factory=list)
    facts: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class TextCard(Card):
    kind = "text"
    title_role: ClassVar[str] = "name"

    pronunciation: str = ""
    part_of_speech: str = ""
    description: str = ""
    definition: str = ""
    value: str = ""
    chips: list[str] = field(default_factory=list)
    rows: list[tuple[str, str]] = field(default_factory=list)
    translation: str = ""
    translation_label: str = ""
    alternatives: list[str] = field(default_factory=list)


@dataclass
class MapTiles:
    width: int
    height: int
    tiles: list[tuple[float, float, bytes]]


@dataclass(kw_only=True)
class HeroCard(Card):
    kind = "hero"
    accent = "blue"

    description: str = ""
    definition: str = ""
    image: bytes | None = None
    image_shape: str = ""
    translation: str = ""
    translation_label: str = ""
    map: MapTiles | None = None
