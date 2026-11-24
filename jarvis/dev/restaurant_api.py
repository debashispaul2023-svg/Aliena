"""API contract checks over the restaurant data layer. No HTTP server started."""

from __future__ import annotations

from jarvis.dev.restaurant_db import RestaurantDB


class RestaurantAPI:
    def __init__(self, db: RestaurantDB) -> None:
        self.db = db

    def get_menu(self) -> tuple[int, dict]:
        return 200, {"menu": self.db.list_menu()}

    def post_contact(self, name: str, message: str) -> tuple[int, dict]:
        try:
            row_id = self.db.add_contact(name, message)
        except ValueError:
            return 400, {"error": "invalid contact"}
        return 201, {"id": row_id}
