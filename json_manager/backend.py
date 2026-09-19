import json
import os


class JsonManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = self.load_json()

    def load_json(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r", encoding='utf-8') as file:
                return json.load(file)
        return {"default": [], "logins": {}}

    def save_json(self):
        with open(self.file_path, "w", encoding='utf-8') as file:
            json.dump(self.data, file, indent=4, ensure_ascii=False)

    def add_administration(self, admin_name, url):
        if admin_name not in self.data["logins"]:
            self.data["logins"][admin_name] = {"url": url, "names": {}}
            self.save_json()

    def get_url(self, admin_name):
        return self.data["logins"][admin_name].get("url", "")

    def add_login(self, admin_name, display_name, login):
        if admin_name in self.data["logins"]:
            self.data["logins"][admin_name].get("names", {})[display_name] = {"login": login}
            self.save_json()

    def remove_login(self, admin_name, display_name):
        if admin_name in self.data["logins"] and display_name in self.data["logins"][admin_name].get("names", {}):
            del self.data["logins"][admin_name].get("names", {})[display_name]
            self.save_json()

    def update_url(self, admin_name, new_url):
        if admin_name in self.data["logins"]:
            self.data["logins"][admin_name]["url"] = new_url
            self.save_json()

    def set_default(self, admin_name, display_name):
        if admin_name in self.data["logins"] and display_name in self.data["logins"][admin_name].get("names", {}):
            self.data["default"] = [admin_name, display_name]
            self.save_json()

    def get_default(self):
        return self.data.get("default", [])

    def remove_administration(self, admin_name):
        if admin_name in self.data["logins"]:
            del self.data["logins"][admin_name]
            self.save_json()
