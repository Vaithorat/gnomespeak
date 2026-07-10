import re


class Auth:
    MIN_KEY_LENGTH = 20

    @staticmethod
    def validate(api_key: str) -> bool:
        if not api_key or not isinstance(api_key, str):
            return False
        if not re.match(r"^sk-[A-Za-z0-9]{" + str(Auth.MIN_KEY_LENGTH) + r",}$", api_key):
            return False
        return True
