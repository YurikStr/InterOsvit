
from database import register_user

result = register_user(
    "test_user",
    "test@example.com",
    "TestPassword123"
)

if result:
    print("Користувача успішно зареєстровано!")
else:
    print("Користувач з таким ім'ям або email вже існує.")
