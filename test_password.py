from werkzeug.security import generate_password_hash, check_password_hash

password = "TestPassword123"

password_hash = generate_password_hash(password)

print("Хеш пароля:")
print(password_hash)

print("\nПеревірка правильного пароля:")
print(check_password_hash(password_hash, "TestPassword123"))

print("\nПеревірка неправильного пароля:")
print(check_password_hash(password_hash, "WrongPassword"))