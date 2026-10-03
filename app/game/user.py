import datetime

from typing import List, Union, Optional

from math import sqrt

from app.game.character import Character, character_from_dict
from app.game.items import Item, item_from_dict

USRXPTOLEVEL = 100
LVLSCALING = 0.09
STORAGE_CAPACITY = 200

class User:
    """| Class used as an interface to data ,Any change made to the class is also made to the data"""

    def __init__(self, data: dict, database=None):
        """Class constructor

        Args:
            data (dict): User dict (see maindatabase file)
            database (_type_): An Instance of Databse (for Updates)
        """
        # Initialization variables
        self.data: dict = data
        self.database = database
        # Inerant variables
        self.id: str = data["_id"]
        if self.id.startswith('b'):
            self.id = self.id[2:-1]
        self.main_characters: List[Character] = [
            character_from_dict(s) for s in data["main_characters"]
        ]
        self.gang_id: Optional[str] = data["gang_id"]
        self.shop_id : Optional[str] = data["shop_id"]
        legacy_storage = [
            character
            for key in (
                "character_storage_1", "character_storage_2", "character_storage_3", "character_storage_4",
                "pcharacter_storage_1", "pcharacter_storage_2", "pcharacter_storage_3", "pcharacter_storage_4",
            )
            for character in data.get(key, [])
        ]
        canonical_storage = data.get("storage_characters", [])
        storage_by_uuid = {}
        for stored in canonical_storage + legacy_storage:
            stand = character_from_dict(stored)
            storage_by_uuid.setdefault(stand.uuid, stand)
        self.storage_characters = list(storage_by_uuid.values())
        self.character_storage_list: List[List[Character]] = [self.storage_characters]
        self.pcharacter_storage_list: List[List[Character]] = []
        self.items: List[Item] = [item_from_dict(s) for s in data["items"]]
        self.achievements: List[int] = data["achievements"]
        self.gang_invites: List[int] = data["gang_invites"]
        self.custom_character: int = data["custom_character"]
        self.fragments: int = data["fragments"]
        # older saves spell it "super_fragements" (the bot's typo); it's rewritten correctly on save
        self.super_fragments: int = data.get("super_fragments", data.get("super_fragements", 0))
        self.xp = data["xp"]
        self.level: int = min(USRXPTOLEVEL,int(LVLSCALING*sqrt(self.xp)))  # cap xp to 100
        self.energy: int = data["energy"]
        self.total_energy: int = int(10 + (self.level//5))
        self.pity: int = data["pity"]
        self.job: dict = data["job"]
        self.prestige: int = data["prestige"]
        self.global_elo: int = data["global_elo"]
        self.missions_level: int = data["missions_level"]
        self.tower_level: int = data["tower_level"]
        self.map_position: List[int] = data["map_position"]
        self.profile_image: str = data["profile_image"]
        self.join_date: datetime.datetime = data["join_date"]
        self.last_full_energy:datetime.datetime = data["last_full_energy"]
        self.last_missions: datetime.datetime = data["last_missions"]
        self.last_wormhole: datetime.datetime = data["last_wormhole"]
        self.last_adventure: datetime.datetime = data["last_adventure"]
        self.last_job: datetime.datetime = data["last_job"]
        self.last_vote: datetime.datetime = data["last_vote"]
        self.last_advert: datetime.datetime = data["last_advert"]
        self.donor_status: datetime.datetime = data["donor_status"]
        self.early_supporter: bool = data["early_supporter"]
        self.achievement_data: dict = data.get("achievement_data", {
            "unlocked": [],
            "counters": {},
        })
        self.quests: dict = data.get("quests", {
            "active_daily": [],
            "active_weekly": [],
            "active_permanent": [],
            "last_daily_reset": datetime.datetime.min,
            "last_weekly_reset": datetime.datetime.min,
            "completed_permanent": [],
        })
        self.story_progress: dict = data.get("story_progress", {
            "current_chapter": 1,
            "current_step": 1,
            "completed_steps": [],
            "rewards_claimed": [],
        })
        self.teams: dict = data.get("teams", {})
        self.is_human = True  # used in fight to determine who is human

    def update_storage(self, storage: List[Character], storage_id: int) -> None:
        """
        Directly modifies the specified storage list with the provided storage.

        Args:
            storage (List[Character]): The new list of characters to replace the old one.
            storage_id (int): The index of the storage list to update.

        Returns:
            None
        """
        # Determine which storage lists to consider based on the user's donator status
        
        self.storage_characters = storage
        self.character_storage_list = [self.storage_characters]
        self.pcharacter_storage_list = []
    
    def update(self) -> None:
        """Update the user info in the database"""
        self.database.update_user(self.to_dict())

    def is_donator(self):
        status = self.early_supporter
        # regular donor status
        status |= self.donor_status >= (
            datetime.datetime.now() + datetime.timedelta(hours=2)
        )
        # answer
        return status
    
    def find_character_by_uuid(self, target_uuid: str):
        """Find a character by UUID across main + all storages.
        Returns (character, source_list, index) or (None, None, None).
        """
        for char_list in [self.main_characters, self.storage_characters]:
            for i, c in enumerate(char_list):
                if c.uuid == target_uuid:
                    return c, char_list, i
        return None, None, None

    def add_to_available_storage(self, character: "Character", skip_main:bool=False):
        if len(self.main_characters) < 3 and not skip_main:
            self.main_characters.append(character)
            return "Main Characters Storage"
        if len(self.storage_characters) >= STORAGE_CAPACITY:
            return False
        self.storage_characters.append(character)
        return "Collection"
    def to_dict(self) -> dict:
        """Convert Class to storable data

        Returns:
            dict: character
        """
        self.data["main_characters"] = [s.to_dict() for s in self.main_characters]
        self.data["gang_id"] = self.gang_id
        self.data["shop_id"] = self.shop_id
        self.data["storage_characters"] = [s.to_dict() for s in self.storage_characters]
        for key in (
            "character_storage_1", "character_storage_2", "character_storage_3", "character_storage_4",
            "pcharacter_storage_1", "pcharacter_storage_2", "pcharacter_storage_3", "pcharacter_storage_4",
        ):
            self.data[key] = []
        self.data["items"] = [s.to_dict() for s in self.items]
        self.data["achievements"] = self.achievements
        self.data["gang_invites"] = self.gang_invites
        self.data["custom_character"] = self.custom_character
        self.data["energy"] = self.energy
        self.data["fragments"] = self.fragments
        self.data["super_fragments"] = self.super_fragments
        self.data.pop("super_fragements", None)
        self.data["pity"] = self.pity
        self.data["xp"] = self.xp
        self.data["job"] = self.job
        self.data["prestige"] = self.prestige
        self.data["global_elo"] = self.global_elo
        self.data["missions_level"] = self.missions_level
        self.data["tower_level"] = self.tower_level
        self.data["map_position"] = self.map_position
        self.data["profile_image"] = self.profile_image
        self.data["join_date"] = self.join_date
        self.data["last_full_energy"] = self.last_full_energy
        self.data["last_missions"] = self.last_missions
        self.data["last_adventure"] = self.last_adventure
        self.data["last_vote"] = self.last_vote
        self.data["last_job"] = self.last_job
        self.data["last_advert"] = self.last_advert
        self.data["last_wormhole"] = self.last_wormhole
        self.data["donor_status"] = self.donor_status
        self.data["early_supporter"] = self.early_supporter
        self.data["achievement_data"] = self.achievement_data
        self.data["quests"] = self.quests
        self.data["story_progress"] = self.story_progress
        self.data["teams"] = self.teams
        return self.data


def create_user(user_id: str):
    data = {
        "_id": user_id,
        "gang_id": None,
        "shop_id":None,
        "main_characters": [],
        "storage_characters": [],
        "items": [],
        "achievements": [],
        "gang_invites": [],
        "custom_character": None,
        "fragments": 0,
        "super_fragments": 0,
        "pity":0,
        "xp": 0,
        "energy": 10,
        "job": None,
        "prestige": 0,
        "global_elo": 0,
        "missions_level": 0,
        "tower_level": 0,
        "map_position": [0, 0],
        "profile_image": "https://i.pinimg.com/originals/77/ba/e4/77bae4f9d1c02f732e9271976539ed48.gif",
        "join_date": (datetime.datetime.now() + datetime.timedelta(hours=2)),
        "last_full_energy": (datetime.datetime.now() + datetime.timedelta(hours=2)),
        "last_missions": datetime.datetime.min,
        "last_adventure": datetime.datetime.min,
        "last_vote": datetime.datetime.min,
        "last_job": datetime.datetime.min,
        "last_advert": datetime.datetime.min,
        "last_wormhole": datetime.datetime.min,
        "donor_status": datetime.datetime.min,
        "early_supporter": False,
        "achievement_data": {
            "unlocked": [],
            "counters": {},
        },
        "quests": {
            "active_daily": [],
            "active_weekly": [],
            "active_permanent": [],
            "last_daily_reset": datetime.datetime.min,
            "last_weekly_reset": datetime.datetime.min,
            "completed_permanent": [],
        },
        "story_progress": {
            "current_chapter": 1,
            "current_step": 1,
            "completed_steps": [],
            "rewards_claimed": [],
        },
        "teams": {},
    }
    return data
