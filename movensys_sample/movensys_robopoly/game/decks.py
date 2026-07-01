"""Chance and Community Chest deck loader (PRD §7.3.6).

Each deck is a JSON file next to this module. Cards are drawn from the
top; after resolution the card moves to the bottom (Hasbro rule) — except
"Get Out of Jail Free" which is held by the player until consumed.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent


@dataclass
class Card:
    id: str
    deck: str
    text: str
    effect: dict[str, Any]

    @classmethod
    def from_json(cls, obj: dict, deck: str) -> "Card":
        return cls(id=obj["id"], deck=deck, text=obj["text"], effect=obj["effect"])


@dataclass
class Deck:
    name: str
    cards: list[Card]
    _rng: random.Random = field(default_factory=random.Random)

    def shuffle(self, seed: int | None = None) -> None:
        if seed is not None:
            self._rng = random.Random(seed)
        self._rng.shuffle(self.cards)

    def draw(self) -> Card:
        """Pop top card. Caller rotates it back with `return_to_bottom` unless
        held (e.g. Get Out of Jail Free)."""
        if not self.cards:
            raise RuntimeError(f"deck {self.name!r} is empty")
        return self.cards.pop(0)

    def return_to_bottom(self, card: Card) -> None:
        self.cards.append(card)

    def __len__(self) -> int:
        return len(self.cards)


def _load(name: str, filename: str, seed: int | None = None) -> Deck:
    path = _DATA_DIR / filename
    data = json.loads(path.read_text())
    cards = [Card.from_json(c, deck=name) for c in data["cards"]]
    deck = Deck(name=name, cards=cards)
    if seed is not None:
        deck.shuffle(seed)
    return deck


def load_chance(seed: int | None = None) -> Deck:
    return _load("chance", "chance.json", seed)


def load_community_chest(seed: int | None = None) -> Deck:
    return _load("community_chest", "community_chest.json", seed)
