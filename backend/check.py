import bcrypt
h = b"$2a$12$WFXc6S7ZxRd9QD6YdenvjuA7NyMoR0wLlN6MhwNVxKf4ZW08rr6yO"
print("hash length:", len(h))
print("match:", bcrypt.checkpw(b"synaptek26027", h))