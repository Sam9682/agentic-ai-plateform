import bcrypt

password = "password"
hash_generated = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
print(hash_generated.decode('utf-8'))
