import json

from app.game.itemabilities import item_specials

import os
_DATA = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(_DATA, "items.json"), "r", encoding="utf-8") as item:
    item_file = json.load(item)["items"]

TORN_DIARY_PAGE = 48
# Refining (app/game/gear.py): each level adds REFINE_STEP of the item's listed stats, up to REFINE_MAX.
REFINE_STEP, REFINE_MAX = 0.10, 5
# Bound to the account: can't be sold (price 0), traded, or listed in a player shop, and never drops.
BOUND_ITEMS = {TORN_DIARY_PAGE}


class Item:
    """This interface to jsoned data THIS CLASS IS NOT INTENDED TO BE CREATED MANUALLY
    Or to be modified.
    """

    def __init__(self, data: dict):

        self.data: dict = data
        self.id: int = data["id"]
        self.name: str = item_file[self.id-1]["name"]
        self.refine: int = max(0, min(REFINE_MAX, int(data.get("refine", 0) or 0)))
        grow = 1 + REFINE_STEP * self.refine
        self.bonus_hp: int = round(item_file[self.id-1]["bonus_hp"] * grow)
        self.bonus_damage: int = round(item_file[self.id-1]["bonus_damage"] * grow)
        self.bonus_speed: int = round(item_file[self.id-1]["bonus_speed"] * grow)
        self.bonus_critical: int = round(item_file[self.id-1]["bonus_critical"] * grow)
        self.bonus_armor:int = round(item_file[self.id-1]["bonus_armor"] * grow)
        self.price: int = item_file[self.id-1]["price"]
        self.prurchasable: bool = item_file[self.id-1]["prurchasable"]
        self.emoji = item_file[self.id-1]["emoji"]
        self.is_equipable = item_file[self.id-1]["is_equipable"]
        self.is_active = item_file[self.id-1]["is_active"]
        self.is_usable = item_file[self.id-1]["is_usable"]
        self.turn_for_ability = item_file[self.id-1]["turn_for_ability"]
        self.special_image = item_file[self.id-1]["special_image"]
        self.taunt: bool = item_file[self.id-1].get("taunt", False)  # the holder taunts like a tank stand
        self.bound: bool = self.id in BOUND_ITEMS
        # Variable
        self.special_meter: int = 0

    def to_dict(self):
        return self.data

    @property
    def label(self) -> str:
        """The name with its refine level: "Dio's Knife +2"."""
        return f"{self.name} +{self.refine}" if self.refine else self.name

    def special(self, stand, allies, ennemies) -> str:
        self.special_meter = 0
        try:
            message = item_specials[f"{self.id}"](stand, allies, ennemies)
        except Exception as e:
            raise(e)
            message = "None"
        return message

    def as_special(self):
        return self.is_active and self.special_meter >= self.turn_for_ability


def spare(items, item_id: int):
    """The copies of item_id in a bag, the least refined first: what selling, crafting and trading give up."""
    return sorted((i for i in items if i.id == item_id), key=lambda i: i.refine)


def item_from_dict(data: dict) -> Item:
    """take a dict and return an Item object

    Args:
        data (dict): normalized data

    Returns:
        Item: Item class
    """
    return Item(data)


def get_item_from_template(template: dict) -> dict:
    return {"id": template["id"]}
