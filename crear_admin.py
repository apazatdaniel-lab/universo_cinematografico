from getpass import getpass
from pathlib import Path
import sqlite3

from werkzeug.security import generate_password_hash

RUTA_BD = Path(__file__).resolve().parent / "cine.db"

nombre = input("Nombre de usuario: ").strip()
contrasena = getpass("Contraseña (no se ve mientras escribes): ")
repetir = getpass("Repite la contraseña: ")

if not nombre:
    print("El nombre de usuario es obligatorio.")
elif len(contrasena) < 8:
    print("La contraseña debe tener al menos 8 caracteres.")
elif contrasena != repetir:
    print("Las contraseñas no coinciden.")
else:
    conexion = sqlite3.connect(RUTA_BD)
    try:
        conexion.execute("""
            INSERT INTO usuarios (nombre_usuario, contrasena_hash, rol)
            VALUES (?, ?, 'admin')
        """, (nombre, generate_password_hash(contrasena)))
        conexion.commit()
        print("Administrador creado correctamente.")
    except sqlite3.IntegrityError:
        print("Ya existe un usuario con ese nombre.")
    except sqlite3.OperationalError:
        print("Falta la tabla usuarios o su columna rol. Ejecuta primero "
              "la app (python app.py) y vuelve a intentarlo.")
    finally:
        conexion.close()