from contextlib import closing
from datetime import date, datetime
from functools import wraps
import os
from pathlib import Path
import sqlite3

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session
)
from werkzeug.security import check_password_hash, generate_password_hash

CARPETA = Path(__file__).resolve().parent
RUTA_BD = CARPETA / "cine.db"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave-local-cine-2026")

@app.before_request
def validar_sesion():
    if request.endpoint == "static" or not session.get("id_usuario"):
        return

    with closing(conectar_bd()) as conexion:
        cuenta = conexion.execute("""
            SELECT rol, activo
            FROM usuarios
            WHERE id_usuario = ?
        """, (session["id_usuario"],)).fetchone()

    if cuenta is None or cuenta["activo"] == 0:
        session.clear()
        flash("Tu cuenta ya no está activa. Inicia sesión de nuevo.", "error")
        return

    # Mantener el rol al día por si un administrador lo cambió
    session["rol"] = cuenta["rol"]

@app.context_processor
def datos_de_sesion():
    pendientes = 0

    if session.get("rol") == "admin":
        with closing(conectar_bd()) as conexion:
            pendientes = conexion.execute("""
                SELECT
                    (SELECT COUNT(*) FROM solicitudes_cambio
                     WHERE estado = 'pendiente')
                  + (SELECT COUNT(*) FROM solicitudes_serie
                     WHERE estado = 'pendiente')
                  + (SELECT COUNT(*) FROM propuestas_pelicula
                     WHERE estado = 'pendiente')
                  + (SELECT COUNT(*) FROM propuestas_serie
                     WHERE estado = 'pendiente')
            """).fetchone()[0]

    return {
        "usuario_actual": session.get("nombre_usuario"),
        "rol_actual": session.get("rol"),
        "solicitudes_pendientes": pendientes
    }

def admin_requerido(vista):
    @wraps(vista)
    def vista_protegida(*args, **kwargs):
        if not session.get("id_usuario"):
            flash("Inicia sesión para continuar.", "error")
            return redirect(url_for("login"))

        if session.get("rol") != "admin":
            flash("No tienes permiso para realizar esta acción.", "error")
            return redirect(url_for("inicio"))

        return vista(*args, **kwargs)

    return vista_protegida

def login_requerido(vista):
    @wraps(vista)
    def vista_protegida(*args, **kwargs):
        if not session.get("id_usuario"):
            flash("Inicia sesión para continuar.", "error")
            return redirect(url_for("login"))

        return vista(*args, **kwargs)

    return vista_protegida

def conectar_bd():
    conexion = sqlite3.connect(RUTA_BD)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def inicializar_bd():
    with closing(conectar_bd()) as conexion:
        # REDISEÑO: los personajes ya no pertenecen a un universo.
        # Se reconstruye la tabla (y su reparto, que está vacío).
        columnas_personajes = [
            columna["name"]
            for columna in conexion.execute(
                "PRAGMA table_info(personajes)"
            ).fetchall()
        ]

        if "id_universo" in columnas_personajes:
            conexion.execute("DROP TABLE IF EXISTS reparto_pelicula")
            conexion.execute("DROP TABLE IF EXISTS reparto_serie")
            conexion.execute("DROP TABLE personajes")
            conexion.commit()
        conexion.executescript("""
            CREATE TABLE IF NOT EXISTS universos (
                id_universo INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                descripcion TEXT
            );

            CREATE TABLE IF NOT EXISTS fases (
                id_fase INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                numero INTEGER NOT NULL CHECK(numero > 0),
                id_universo INTEGER NOT NULL,
                UNIQUE (id_universo, numero),
                FOREIGN KEY (id_universo)
                    REFERENCES universos(id_universo)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS peliculas (
                id_pelicula INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                anio_estreno INTEGER,
                duracion_minutos INTEGER,
                sinopsis TEXT,
                portada TEXT,
                trailer_url TEXT,
                id_fase INTEGER,
                FOREIGN KEY (id_fase)
                    REFERENCES fases(id_fase)
                                        ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS series (
                id_serie INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                anio_inicio INTEGER,
                temporadas INTEGER CHECK(temporadas IS NULL OR temporadas > 0),
                sinopsis TEXT,
                portada TEXT,
                trailer_url TEXT,
                id_fase INTEGER,
                id_universo INTEGER NOT NULL,
                FOREIGN KEY (id_fase)
                    REFERENCES fases(id_fase)
                    ON DELETE SET NULL,
                                FOREIGN KEY (id_universo)
                    REFERENCES universos(id_universo)
                    ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS solicitudes_cambio (
                id_solicitud INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario INTEGER NOT NULL,
                id_pelicula INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                anio_estreno INTEGER,
                duracion_minutos INTEGER,
                sinopsis TEXT,
                portada TEXT,
                trailer_url TEXT,
                id_fase INTEGER,
                id_universo INTEGER NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'aprobada', 'rechazada')),
                fecha_solicitud TEXT NOT NULL DEFAULT (datetime('now')),
                id_admin_revisor INTEGER,
                fecha_revision TEXT,
                FOREIGN KEY (id_usuario)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_pelicula)
                    REFERENCES peliculas(id_pelicula)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_fase)
                    REFERENCES fases(id_fase)
                    ON DELETE SET NULL,
                FOREIGN KEY (id_universo)
                    REFERENCES universos(id_universo)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_admin_revisor)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE SET NULL
            );

                        CREATE UNIQUE INDEX IF NOT EXISTS idx_solicitud_pendiente
                ON solicitudes_cambio (id_usuario, id_pelicula)
                WHERE estado = 'pendiente';

            CREATE TABLE IF NOT EXISTS solicitudes_serie (
                id_solicitud INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario INTEGER NOT NULL,
                id_serie INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                anio_inicio INTEGER,
                temporadas INTEGER
                    CHECK (temporadas IS NULL OR temporadas > 0),
                sinopsis TEXT,
                portada TEXT,
                trailer_url TEXT,
                id_fase INTEGER,
                id_universo INTEGER NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'aprobada', 'rechazada')),
                fecha_solicitud TEXT NOT NULL DEFAULT (datetime('now')),
                id_admin_revisor INTEGER,
                fecha_revision TEXT,
                FOREIGN KEY (id_usuario)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_serie)
                    REFERENCES series(id_serie)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_fase)
                    REFERENCES fases(id_fase)
                    ON DELETE SET NULL,
                FOREIGN KEY (id_universo)
                    REFERENCES universos(id_universo)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_admin_revisor)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE SET NULL
            );

                        CREATE UNIQUE INDEX IF NOT EXISTS idx_solicitud_serie_pendiente
                ON solicitudes_serie (id_usuario, id_serie)
                WHERE estado = 'pendiente';

            CREATE TABLE IF NOT EXISTS propuestas_pelicula (
                id_propuesta INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                anio_estreno INTEGER,
                duracion_minutos INTEGER,
                sinopsis TEXT,
                portada TEXT,
                trailer_url TEXT,
                id_fase INTEGER,
                id_universo INTEGER NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'aprobada', 'rechazada')),
                fecha_solicitud TEXT NOT NULL DEFAULT (datetime('now')),
                id_admin_revisor INTEGER,
                fecha_revision TEXT,
                motivo_rechazo TEXT,
                FOREIGN KEY (id_usuario)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_fase)
                    REFERENCES fases(id_fase)
                    ON DELETE SET NULL,
                FOREIGN KEY (id_universo)
                    REFERENCES universos(id_universo)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_admin_revisor)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE SET NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_propuesta_pelicula_pendiente
                ON propuestas_pelicula (id_usuario, lower(titulo))
                WHERE estado = 'pendiente';

            CREATE TABLE IF NOT EXISTS propuestas_serie (
                id_propuesta INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                anio_inicio INTEGER,
                temporadas INTEGER
                    CHECK (temporadas IS NULL OR temporadas > 0),
                sinopsis TEXT,
                portada TEXT,
                trailer_url TEXT,
                id_fase INTEGER,
                id_universo INTEGER NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'aprobada', 'rechazada')),
                fecha_solicitud TEXT NOT NULL DEFAULT (datetime('now')),
                id_admin_revisor INTEGER,
                fecha_revision TEXT,
                motivo_rechazo TEXT,
                FOREIGN KEY (id_usuario)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_fase)
                    REFERENCES fases(id_fase)
                    ON DELETE SET NULL,
                FOREIGN KEY (id_universo)
                    REFERENCES universos(id_universo)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_admin_revisor)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE SET NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_propuesta_serie_pendiente
                ON propuestas_serie (id_usuario, lower(titulo))
                WHERE estado = 'pendiente';

            CREATE TABLE IF NOT EXISTS valoraciones_pelicula (
                id_valoracion INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario INTEGER NOT NULL,
                id_pelicula INTEGER NOT NULL,
                puntuacion INTEGER NOT NULL
                    CHECK (puntuacion BETWEEN 1 AND 5),
                comentario TEXT
                    CHECK (comentario IS NULL OR length(comentario) <= 500),
                fecha TEXT NOT NULL DEFAULT (datetime('now')),
                fecha_edicion TEXT,
                UNIQUE (id_usuario, id_pelicula),
                FOREIGN KEY (id_usuario)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_pelicula)
                    REFERENCES peliculas(id_pelicula)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS valoraciones_serie (
                id_valoracion INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario INTEGER NOT NULL,
                id_serie INTEGER NOT NULL,
                puntuacion INTEGER NOT NULL
                    CHECK (puntuacion BETWEEN 1 AND 5),
                comentario TEXT
                    CHECK (comentario IS NULL OR length(comentario) <= 500),
                fecha TEXT NOT NULL DEFAULT (datetime('now')),
                fecha_edicion TEXT,
                UNIQUE (id_usuario, id_serie),
                FOREIGN KEY (id_usuario)
                    REFERENCES usuarios(id_usuario)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_serie)
                    REFERENCES series(id_serie)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS actores (
                id_actor INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                fecha_nacimiento TEXT,
                nacionalidad TEXT,
                biografia TEXT,
                foto TEXT
            );

            CREATE TABLE IF NOT EXISTS personajes (
                id_personaje INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                alias TEXT,
                descripcion TEXT,
                imagen TEXT
            );

            CREATE TABLE IF NOT EXISTS reparto_pelicula (
                id_reparto INTEGER PRIMARY KEY AUTOINCREMENT,
                id_pelicula INTEGER NOT NULL,
                id_actor INTEGER NOT NULL,
                id_personaje INTEGER NOT NULL,
                UNIQUE (id_pelicula, id_actor, id_personaje),
                FOREIGN KEY (id_pelicula)
                    REFERENCES peliculas(id_pelicula)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_actor)
                    REFERENCES actores(id_actor)
                    ON DELETE RESTRICT,
                FOREIGN KEY (id_personaje)
                    REFERENCES personajes(id_personaje)
                    ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS reparto_serie (
                id_reparto INTEGER PRIMARY KEY AUTOINCREMENT,
                id_serie INTEGER NOT NULL,
                id_actor INTEGER NOT NULL,
                id_personaje INTEGER NOT NULL,
                UNIQUE (id_serie, id_actor, id_personaje),
                FOREIGN KEY (id_serie)
                    REFERENCES series(id_serie)
                    ON DELETE CASCADE,
                FOREIGN KEY (id_actor)
                    REFERENCES actores(id_actor)
                    ON DELETE RESTRICT,
                FOREIGN KEY (id_personaje)
                    REFERENCES personajes(id_personaje)
                    ON DELETE RESTRICT
            );
        """)
        # MIGRACIÓN: agregar la relación directa entre películas y universos
        columnas = [
            columna["name"]
            for columna in conexion.execute(
                "PRAGMA table_info(peliculas)"
            ).fetchall()
        ]

        if "id_universo" not in columnas:
            conexion.execute("""
                ALTER TABLE peliculas
                ADD COLUMN id_universo INTEGER
                REFERENCES universos(id_universo)
                ON DELETE SET NULL
            """)

        # Recuperar el universo de las películas que ya tienen una fase
        conexion.execute("""
            UPDATE peliculas
            SET id_universo = (
                SELECT fases.id_universo
                FROM fases
                WHERE fases.id_fase = peliculas.id_fase
            )
            WHERE id_universo IS NULL
              AND id_fase IS NOT NULL
        """)

        # Crear un universo de respaldo para películas sin universo asignado
        conexion.execute("""
            INSERT OR IGNORE INTO universos (nombre, descripcion)
            VALUES (
                'Sin clasificar',
                'Universo temporal para películas pendientes de clasificación'
            )
        """)

        universo_respaldo = conexion.execute("""
            SELECT id_universo
            FROM universos
            WHERE nombre = 'Sin clasificar'
        """).fetchone()

        conexion.execute("""
            UPDATE peliculas
            SET id_universo = ?
            WHERE id_universo IS NULL
        """, (universo_respaldo["id_universo"],))

        # MIGRACIÓN: motivo de rechazo en las solicitudes
        for tabla in ("solicitudes_cambio", "solicitudes_serie"):
            columnas_tabla = [
                columna["name"]
                for columna in conexion.execute(
                    f"PRAGMA table_info({tabla})"
                ).fetchall()
            ]

            if "motivo_rechazo" not in columnas_tabla:
                conexion.execute(
                    f"ALTER TABLE {tabla} ADD COLUMN motivo_rechazo TEXT"
                )

        # MIGRACIÓN: cuentas activas o desactivadas
        columnas_usuarios = [
            columna["name"]
            for columna in conexion.execute(
                "PRAGMA table_info(usuarios)"
            ).fetchall()
        ]

        if "activo" not in columnas_usuarios:
            conexion.execute("""
                ALTER TABLE usuarios
                ADD COLUMN activo INTEGER NOT NULL DEFAULT 1
                CHECK (activo IN (0, 1))
            """)

        conexion.commit()

inicializar_bd()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nombre = request.form.get("nombre_usuario", "").strip()
        contrasena = request.form.get("contrasena", "")

        with closing(conectar_bd()) as conexion:
            usuario = conexion.execute("""
                SELECT id_usuario, nombre_usuario,
                       contrasena_hash, rol, activo
                FROM usuarios
                WHERE nombre_usuario = ?
            """, (nombre,)).fetchone()

        if usuario is None or not check_password_hash(
            usuario["contrasena_hash"], contrasena
        ):
            flash("Usuario o contraseña incorrectos.", "error")
            return redirect(url_for("login"))

        if usuario["activo"] == 0:
            flash(
                "Esta cuenta está desactivada. "
                "Contacta a un administrador.",
                "error"
            )
            return redirect(url_for("login"))

        session.clear()
        session["id_usuario"] = usuario["id_usuario"]
        session["nombre_usuario"] = usuario["nombre_usuario"]
        session["rol"] = usuario["rol"]

        flash("Sesión iniciada correctamente.", "exito")
        return redirect(url_for("inicio"))

    return render_template("login.html")

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if session.get("id_usuario"):
        return redirect(url_for("inicio"))

    if request.method == "POST":
        nombre = request.form.get("nombre_usuario", "").strip()
        contrasena = request.form.get("contrasena", "")
        repetir = request.form.get("repetir_contrasena", "")

        if not 3 <= len(nombre) <= 30:
            flash(
                "El nombre de usuario debe tener entre 3 y 30 caracteres.",
                "error"
            )
            return redirect(url_for("registro"))

        if len(contrasena) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
            return redirect(url_for("registro"))

        if contrasena != repetir:
            flash("Las contraseñas no coinciden.", "error")
            return redirect(url_for("registro"))

        try:
            with closing(conectar_bd()) as conexion:
                existente = conexion.execute("""
                    SELECT 1
                    FROM usuarios
                    WHERE lower(nombre_usuario) = lower(?)
                """, (nombre,)).fetchone()

                if existente:
                    flash("Ese nombre de usuario ya está en uso.", "error")
                    return redirect(url_for("registro"))

                conexion.execute("""
                    INSERT INTO usuarios (
                        nombre_usuario, contrasena_hash, rol
                    )
                    VALUES (?, ?, 'usuario')
                """, (nombre, generate_password_hash(contrasena)))
                conexion.commit()

        except sqlite3.IntegrityError:
            flash("Ese nombre de usuario ya está en uso.", "error")
            return redirect(url_for("registro"))

        flash("Cuenta creada correctamente. Ahora inicia sesión.", "exito")
        return redirect(url_for("login"))

    return render_template("registro.html")

@app.route("/administradores/<int:id_usuario>/quitar-admin", methods=["POST"])
@admin_requerido
def quitar_admin(id_usuario):
    if id_usuario == session["id_usuario"]:
        flash("No puedes cambiar tu propia cuenta.", "error")
        return redirect(url_for("administradores"))

    with closing(conectar_bd()) as conexion:
        cuenta = conexion.execute("""
            SELECT rol FROM usuarios WHERE id_usuario = ?
        """, (id_usuario,)).fetchone()

        if cuenta is None:
            flash("No se encontró esa cuenta.", "error")
            return redirect(url_for("administradores"))

        if cuenta["rol"] != "admin":
            flash("Esa cuenta no es de administrador.", "error")
            return redirect(url_for("administradores"))

        resultado = conexion.execute("""
            UPDATE usuarios
            SET rol = 'usuario'
            WHERE id_usuario = ?
              AND rol = 'admin'
              AND (
                    activo = 0
                    OR (SELECT COUNT(*) FROM usuarios
                        WHERE rol = 'admin' AND activo = 1) > 1
                  )
        """, (id_usuario,))

        if resultado.rowcount == 0:
            flash(
                "No se puede: debe quedar al menos un administrador activo.",
                "error"
            )
        else:
            conexion.commit()
            flash("La cuenta ahora es de usuario.", "exito")

    return redirect(url_for("administradores"))


@app.route("/administradores/<int:id_usuario>/desactivar", methods=["POST"])
@admin_requerido
def desactivar_cuenta(id_usuario):
    if id_usuario == session["id_usuario"]:
        flash("No puedes cambiar tu propia cuenta.", "error")
        return redirect(url_for("administradores"))

    with closing(conectar_bd()) as conexion:
        cuenta = conexion.execute("""
            SELECT activo FROM usuarios WHERE id_usuario = ?
        """, (id_usuario,)).fetchone()

        if cuenta is None:
            flash("No se encontró esa cuenta.", "error")
            return redirect(url_for("administradores"))

        if cuenta["activo"] == 0:
            flash("Esa cuenta ya está desactivada.", "error")
            return redirect(url_for("administradores"))

        resultado = conexion.execute("""
            UPDATE usuarios
            SET activo = 0
            WHERE id_usuario = ?
              AND activo = 1
              AND (
                    rol != 'admin'
                    OR (SELECT COUNT(*) FROM usuarios
                        WHERE rol = 'admin' AND activo = 1) > 1
                  )
        """, (id_usuario,))

        if resultado.rowcount == 0:
            flash(
                "No se puede: debe quedar al menos un administrador activo.",
                "error"
            )
        else:
            conexion.commit()
            flash("Cuenta desactivada.", "exito")

    return redirect(url_for("administradores"))


@app.route("/administradores/<int:id_usuario>/activar", methods=["POST"])
@admin_requerido
def activar_cuenta(id_usuario):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            UPDATE usuarios
            SET activo = 1
            WHERE id_usuario = ?
              AND activo = 0
        """, (id_usuario,))

        if resultado.rowcount == 0:
            flash("Esa cuenta no existe o ya está activa.", "error")
        else:
            conexion.commit()
            flash("Cuenta activada.", "exito")

    return redirect(url_for("administradores"))

@app.route("/administradores", methods=["GET", "POST"])
@admin_requerido
def administradores():
    if request.method == "POST":
        nombre = request.form.get("nombre_usuario", "").strip()
        contrasena = request.form.get("contrasena", "")
        repetir = request.form.get("repetir_contrasena", "")

        if not 3 <= len(nombre) <= 30:
            flash(
                "El nombre de usuario debe tener entre 3 y 30 caracteres.",
                "error"
            )
            return redirect(url_for("administradores"))

        if len(contrasena) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
            return redirect(url_for("administradores"))

        if contrasena != repetir:
            flash("Las contraseñas no coinciden.", "error")
            return redirect(url_for("administradores"))

        try:
            with closing(conectar_bd()) as conexion:
                existente = conexion.execute("""
                    SELECT 1
                    FROM usuarios
                    WHERE lower(nombre_usuario) = lower(?)
                """, (nombre,)).fetchone()

                if existente:
                    flash("Ese nombre de usuario ya está en uso.", "error")
                    return redirect(url_for("administradores"))

                conexion.execute("""
                    INSERT INTO usuarios (
                        nombre_usuario, contrasena_hash, rol
                    )
                    VALUES (?, ?, 'admin')
                """, (nombre, generate_password_hash(contrasena)))
                conexion.commit()

        except sqlite3.IntegrityError:
            flash("Ese nombre de usuario ya está en uso.", "error")
            return redirect(url_for("administradores"))

        flash("Administrador creado correctamente.", "exito")
        return redirect(url_for("administradores"))

    with closing(conectar_bd()) as conexion:
        cuentas = conexion.execute("""
            SELECT id_usuario, nombre_usuario, rol, activo
            FROM usuarios
            ORDER BY rol, nombre_usuario
        """).fetchall()

    return render_template("administradores.html", cuentas=cuentas)

@app.route(
    "/mis-solicitudes/pelicula/<int:id_solicitud>/cancelar",
    methods=["POST"]
)
@login_requerido
def cancelar_solicitud(id_solicitud):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM solicitudes_cambio
            WHERE id_solicitud = ?
              AND id_usuario = ?
              AND estado = 'pendiente'
        """, (id_solicitud, session["id_usuario"]))

        if resultado.rowcount == 0:
            flash(
                "No se pudo cancelar: la solicitud no existe, "
                "no es tuya o ya fue revisada.",
                "error"
            )
        else:
            conexion.commit()
            flash("Solicitud cancelada.", "exito")

    return redirect(url_for("mis_solicitudes"))


@app.route(
    "/mis-solicitudes/serie/<int:id_solicitud>/cancelar",
    methods=["POST"]
)
@login_requerido
def cancelar_solicitud_serie(id_solicitud):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM solicitudes_serie
            WHERE id_solicitud = ?
              AND id_usuario = ?
              AND estado = 'pendiente'
        """, (id_solicitud, session["id_usuario"]))

        if resultado.rowcount == 0:
            flash(
                "No se pudo cancelar: la solicitud no existe, "
                "no es tuya o ya fue revisada.",
                "error"
            )
        else:
            conexion.commit()
            flash("Solicitud cancelada.", "exito")

    return redirect(url_for("mis_solicitudes"))

@app.route(
    "/mis-solicitudes/propuesta-pelicula/<int:id_propuesta>/cancelar",
    methods=["POST"]
)
@login_requerido
def cancelar_propuesta_pelicula(id_propuesta):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM propuestas_pelicula
            WHERE id_propuesta = ?
              AND id_usuario = ?
              AND estado = 'pendiente'
        """, (id_propuesta, session["id_usuario"]))

        if resultado.rowcount == 0:
            flash(
                "No se pudo cancelar: la propuesta no existe, "
                "no es tuya o ya fue revisada.",
                "error"
            )
        else:
            conexion.commit()
            flash("Propuesta cancelada.", "exito")

    return redirect(url_for("mis_solicitudes"))


@app.route(
    "/mis-solicitudes/propuesta-serie/<int:id_propuesta>/cancelar",
    methods=["POST"]
)
@login_requerido
def cancelar_propuesta_serie(id_propuesta):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM propuestas_serie
            WHERE id_propuesta = ?
              AND id_usuario = ?
              AND estado = 'pendiente'
        """, (id_propuesta, session["id_usuario"]))

        if resultado.rowcount == 0:
            flash(
                "No se pudo cancelar: la propuesta no existe, "
                "no es tuya o ya fue revisada.",
                "error"
            )
        else:
            conexion.commit()
            flash("Propuesta cancelada.", "exito")

    return redirect(url_for("mis_solicitudes"))

@app.route("/mis-solicitudes")
@login_requerido
def mis_solicitudes():
    id_usuario = session["id_usuario"]

    with closing(conectar_bd()) as conexion:
        solicitudes_usuario = conexion.execute("""
            SELECT 'Película' AS tipo, s.id_solicitud, s.estado,
                   s.fecha_solicitud, s.fecha_revision,
                   s.motivo_rechazo,
                   p.titulo AS titulo
            FROM solicitudes_cambio s
            JOIN peliculas p ON s.id_pelicula = p.id_pelicula
            WHERE s.id_usuario = ?
            UNION ALL
            SELECT 'Serie' AS tipo, s.id_solicitud, s.estado,
                   s.fecha_solicitud, s.fecha_revision,
                   s.motivo_rechazo,
                   se.titulo AS titulo
            FROM solicitudes_serie s
            JOIN series se ON s.id_serie = se.id_serie
            WHERE s.id_usuario = ?
            UNION ALL
            SELECT 'Película nueva' AS tipo,
                   s.id_propuesta AS id_solicitud, s.estado,
                   s.fecha_solicitud, s.fecha_revision,
                   s.motivo_rechazo,
                   s.titulo AS titulo
            FROM propuestas_pelicula s
            WHERE s.id_usuario = ?
            UNION ALL
            SELECT 'Serie nueva' AS tipo,
                   s.id_propuesta AS id_solicitud, s.estado,
                   s.fecha_solicitud, s.fecha_revision,
                   s.motivo_rechazo,
                   s.titulo AS titulo
            FROM propuestas_serie s
            WHERE s.id_usuario = ?
            ORDER BY fecha_solicitud DESC
        """, (id_usuario, id_usuario, id_usuario, id_usuario)).fetchall()

    return render_template(
        "mis_solicitudes.html",
        solicitudes=solicitudes_usuario
    )

@app.route("/solicitudes")
@admin_requerido
def solicitudes():
    with closing(conectar_bd()) as conexion:
        pendientes = conexion.execute("""
            SELECT s.*,
                   u.nombre_usuario AS solicitante,
                   p.titulo AS actual_titulo,
                   p.anio_estreno AS actual_anio,
                   p.duracion_minutos AS actual_duracion,
                   p.sinopsis AS actual_sinopsis,
                   p.portada AS actual_portada,
                   p.trailer_url AS actual_trailer,
                   uni_a.nombre AS actual_universo,
                   fa_a.nombre AS actual_fase,
                   uni_p.nombre AS propuesto_universo,
                   fa_p.nombre AS propuesto_fase
            FROM solicitudes_cambio s
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            JOIN peliculas p ON s.id_pelicula = p.id_pelicula
            LEFT JOIN universos uni_a
                ON p.id_universo = uni_a.id_universo
            LEFT JOIN fases fa_a ON p.id_fase = fa_a.id_fase
            LEFT JOIN universos uni_p
                ON s.id_universo = uni_p.id_universo
            LEFT JOIN fases fa_p ON s.id_fase = fa_p.id_fase
            WHERE s.estado = 'pendiente'
            ORDER BY s.fecha_solicitud
        """).fetchall()

        pendientes_series = conexion.execute("""
            SELECT s.*,
                   u.nombre_usuario AS solicitante,
                   se.titulo AS actual_titulo,
                   se.anio_inicio AS actual_anio,
                   se.temporadas AS actual_temporadas,
                   se.sinopsis AS actual_sinopsis,
                   se.portada AS actual_portada,
                   se.trailer_url AS actual_trailer,
                   uni_a.nombre AS actual_universo,
                   fa_a.nombre AS actual_fase,
                   uni_p.nombre AS propuesto_universo,
                   fa_p.nombre AS propuesto_fase
            FROM solicitudes_serie s
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            JOIN series se ON s.id_serie = se.id_serie
            LEFT JOIN universos uni_a
                ON se.id_universo = uni_a.id_universo
            LEFT JOIN fases fa_a ON se.id_fase = fa_a.id_fase
            LEFT JOIN universos uni_p
                ON s.id_universo = uni_p.id_universo
            LEFT JOIN fases fa_p ON s.id_fase = fa_p.id_fase
            WHERE s.estado = 'pendiente'
            ORDER BY s.fecha_solicitud
        """).fetchall()

        propuestas_peliculas = conexion.execute("""
            SELECT s.*,
                   u.nombre_usuario AS solicitante,
                   uni.nombre AS universo,
                   fa.nombre AS fase
            FROM propuestas_pelicula s
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            LEFT JOIN universos uni ON s.id_universo = uni.id_universo
            LEFT JOIN fases fa ON s.id_fase = fa.id_fase
            WHERE s.estado = 'pendiente'
            ORDER BY s.fecha_solicitud
        """).fetchall()

        propuestas_series = conexion.execute("""
            SELECT s.*,
                   u.nombre_usuario AS solicitante,
                   uni.nombre AS universo,
                   fa.nombre AS fase
            FROM propuestas_serie s
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            LEFT JOIN universos uni ON s.id_universo = uni.id_universo
            LEFT JOIN fases fa ON s.id_fase = fa.id_fase
            WHERE s.estado = 'pendiente'
            ORDER BY s.fecha_solicitud
        """).fetchall()

        historial = conexion.execute("""
            SELECT 'Película' AS tipo, s.estado, s.fecha_revision,
                   s.motivo_rechazo,
                   p.titulo AS titulo,
                   u.nombre_usuario AS solicitante,
                   r.nombre_usuario AS revisor
            FROM solicitudes_cambio s
            JOIN peliculas p ON s.id_pelicula = p.id_pelicula
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            LEFT JOIN usuarios r ON s.id_admin_revisor = r.id_usuario
            WHERE s.estado != 'pendiente'
            UNION ALL
            SELECT 'Serie' AS tipo, s.estado, s.fecha_revision,
                   s.motivo_rechazo,
                   se.titulo AS titulo,
                   u.nombre_usuario AS solicitante,
                   r.nombre_usuario AS revisor
            FROM solicitudes_serie s
            JOIN series se ON s.id_serie = se.id_serie
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            LEFT JOIN usuarios r ON s.id_admin_revisor = r.id_usuario
            WHERE s.estado != 'pendiente'
            UNION ALL
            SELECT 'Película nueva' AS tipo, s.estado, s.fecha_revision,
                   s.motivo_rechazo,
                   s.titulo AS titulo,
                   u.nombre_usuario AS solicitante,
                   r.nombre_usuario AS revisor
            FROM propuestas_pelicula s
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            LEFT JOIN usuarios r ON s.id_admin_revisor = r.id_usuario
            WHERE s.estado != 'pendiente'
            UNION ALL
            SELECT 'Serie nueva' AS tipo, s.estado, s.fecha_revision,
                   s.motivo_rechazo,
                   s.titulo AS titulo,
                   u.nombre_usuario AS solicitante,
                   r.nombre_usuario AS revisor
            FROM propuestas_serie s
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            LEFT JOIN usuarios r ON s.id_admin_revisor = r.id_usuario
            WHERE s.estado != 'pendiente'
            ORDER BY fecha_revision DESC
            LIMIT 10
        """).fetchall()

    return render_template(
        "solicitudes.html",
        pendientes=pendientes,
        pendientes_series=pendientes_series,
        propuestas_peliculas=propuestas_peliculas,
        propuestas_series=propuestas_series,
        historial=historial
    )


@app.route("/solicitudes/<int:id_solicitud>/aprobar", methods=["POST"])
@admin_requerido
def aprobar_solicitud(id_solicitud):
    with closing(conectar_bd()) as conexion:
        solicitud = conexion.execute("""
            SELECT * FROM solicitudes_cambio
            WHERE id_solicitud = ?
        """, (id_solicitud,)).fetchone()

        if solicitud is None:
            flash("No se encontró esa solicitud.", "error")
            return redirect(url_for("solicitudes"))

        if solicitud["estado"] != "pendiente":
            flash("Esa solicitud ya fue revisada.", "error")
            return redirect(url_for("solicitudes"))

        # Volver a validar: el universo o la fase pudieron cambiar
        # desde que el usuario envió la solicitud
        universo = conexion.execute("""
            SELECT id_universo FROM universos
            WHERE id_universo = ?
        """, (solicitud["id_universo"],)).fetchone()

        if universo is None:
            flash(
                "El universo propuesto ya no existe. "
                "Rechaza la solicitud.",
                "error"
            )
            return redirect(url_for("solicitudes"))

        if solicitud["id_fase"] is not None:
            fase = conexion.execute("""
                SELECT id_universo FROM fases
                WHERE id_fase = ?
            """, (solicitud["id_fase"],)).fetchone()

            if fase is None or fase["id_universo"] != solicitud["id_universo"]:
                flash(
                    "La fase propuesta ya no es válida para ese universo. "
                    "Rechaza la solicitud.",
                    "error"
                )
                return redirect(url_for("solicitudes"))

        try:
            conexion.execute("""
                UPDATE peliculas
                SET titulo = ?, anio_estreno = ?,
                    duracion_minutos = ?, sinopsis = ?,
                    portada = ?, trailer_url = ?,
                    id_fase = ?, id_universo = ?
                WHERE id_pelicula = ?
            """, (
                solicitud["titulo"], solicitud["anio_estreno"],
                solicitud["duracion_minutos"], solicitud["sinopsis"],
                solicitud["portada"], solicitud["trailer_url"],
                solicitud["id_fase"], solicitud["id_universo"],
                solicitud["id_pelicula"]
            ))

            conexion.execute("""
                UPDATE solicitudes_cambio
                SET estado = 'aprobada',
                    id_admin_revisor = ?,
                    fecha_revision = datetime('now')
                WHERE id_solicitud = ?
                  AND estado = 'pendiente'
            """, (session["id_usuario"], id_solicitud))

            conexion.commit()

        except sqlite3.IntegrityError:
            flash("No se pudo aplicar el cambio.", "error")
            return redirect(url_for("solicitudes"))

    flash("Solicitud aprobada: la película fue actualizada.", "exito")
    return redirect(url_for("solicitudes"))


@app.route("/solicitudes/<int:id_solicitud>/rechazar", methods=["POST"])
@admin_requerido
def rechazar_solicitud(id_solicitud):
    motivo = request.form.get("motivo", "").strip()

    if not 3 <= len(motivo) <= 300:
        flash(
            "Escribe el motivo del rechazo (entre 3 y 300 caracteres).",
            "error"
        )
        return redirect(url_for("solicitudes"))

    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            UPDATE solicitudes_cambio
            SET estado = 'rechazada',
                motivo_rechazo = ?,
                id_admin_revisor = ?,
                fecha_revision = datetime('now')
            WHERE id_solicitud = ?
              AND estado = 'pendiente'
        """, (motivo, session["id_usuario"], id_solicitud))

        if resultado.rowcount == 0:
            flash("Esa solicitud no existe o ya fue revisada.", "error")
        else:
            conexion.commit()
            flash("Solicitud rechazada. La película no cambió.", "exito")

    return redirect(url_for("solicitudes"))

@app.route(
    "/solicitudes-serie/<int:id_solicitud>/aprobar",
    methods=["POST"]
)
@admin_requerido
def aprobar_solicitud_serie(id_solicitud):
    with closing(conectar_bd()) as conexion:
        solicitud = conexion.execute("""
            SELECT * FROM solicitudes_serie
            WHERE id_solicitud = ?
        """, (id_solicitud,)).fetchone()

        if solicitud is None:
            flash("No se encontró esa solicitud.", "error")
            return redirect(url_for("solicitudes"))

        if solicitud["estado"] != "pendiente":
            flash("Esa solicitud ya fue revisada.", "error")
            return redirect(url_for("solicitudes"))

        # Volver a validar: el universo o la fase pudieron cambiar
        # desde que el usuario envió la solicitud
        universo = conexion.execute("""
            SELECT id_universo FROM universos
            WHERE id_universo = ?
        """, (solicitud["id_universo"],)).fetchone()

        if universo is None:
            flash(
                "El universo propuesto ya no existe. "
                "Rechaza la solicitud.",
                "error"
            )
            return redirect(url_for("solicitudes"))

        if solicitud["id_fase"] is not None:
            fase = conexion.execute("""
                SELECT id_universo FROM fases
                WHERE id_fase = ?
            """, (solicitud["id_fase"],)).fetchone()

            if fase is None or fase["id_universo"] != solicitud["id_universo"]:
                flash(
                    "La fase propuesta ya no es válida para ese universo. "
                    "Rechaza la solicitud.",
                    "error"
                )
                return redirect(url_for("solicitudes"))

        try:
            conexion.execute("""
                UPDATE series
                SET titulo = ?, anio_inicio = ?, temporadas = ?,
                    sinopsis = ?, portada = ?, trailer_url = ?,
                    id_fase = ?, id_universo = ?
                WHERE id_serie = ?
            """, (
                solicitud["titulo"], solicitud["anio_inicio"],
                solicitud["temporadas"], solicitud["sinopsis"],
                solicitud["portada"], solicitud["trailer_url"],
                solicitud["id_fase"], solicitud["id_universo"],
                solicitud["id_serie"]
            ))

            conexion.execute("""
                UPDATE solicitudes_serie
                SET estado = 'aprobada',
                    id_admin_revisor = ?,
                    fecha_revision = datetime('now')
                WHERE id_solicitud = ?
                  AND estado = 'pendiente'
            """, (session["id_usuario"], id_solicitud))

            conexion.commit()

        except sqlite3.IntegrityError:
            flash("No se pudo aplicar el cambio.", "error")
            return redirect(url_for("solicitudes"))

    flash("Solicitud aprobada: la serie fue actualizada.", "exito")
    return redirect(url_for("solicitudes"))


@app.route(
    "/solicitudes-serie/<int:id_solicitud>/rechazar",
    methods=["POST"]
)
@admin_requerido
def rechazar_solicitud_serie(id_solicitud):
    motivo = request.form.get("motivo", "").strip()

    if not 3 <= len(motivo) <= 300:
        flash(
            "Escribe el motivo del rechazo (entre 3 y 300 caracteres).",
            "error"
        )
        return redirect(url_for("solicitudes"))

    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            UPDATE solicitudes_serie
            SET estado = 'rechazada',
                motivo_rechazo = ?,
                id_admin_revisor = ?,
                fecha_revision = datetime('now')
            WHERE id_solicitud = ?
              AND estado = 'pendiente'
        """, (motivo, session["id_usuario"], id_solicitud))

        if resultado.rowcount == 0:
            flash("Esa solicitud no existe o ya fue revisada.", "error")
        else:
            conexion.commit()
            flash("Solicitud rechazada. La serie no cambió.", "exito")

    return redirect(url_for("solicitudes"))

def es_nacionalidad_valida(texto):
    if len(texto) > 60:
        return False

    tiene_letra = any(c.isalpha() for c in texto)
    solo_permitidos = all(c.isalpha() or c in " -'." for c in texto)

    return tiene_letra and solo_permitidos

@app.route("/actores")
def catalogo_actores():
    with closing(conectar_bd()) as conexion:
        actores = conexion.execute("""
            SELECT * FROM actores ORDER BY nombre
        """).fetchall()

    return render_template("actores.html", actores=actores)


@app.route("/actores/agregar")
@admin_requerido
def agregar_actor():
    return render_template("agregar_actor.html")


@app.route("/actores/nuevo", methods=["POST"])
@admin_requerido
def nuevo_actor():
    nombre = request.form.get("nombre", "").strip()
    fecha_texto = request.form.get("fecha_nacimiento", "").strip()
    nacionalidad = request.form.get("nacionalidad", "").strip()
    biografia = request.form.get("biografia", "").strip()
    foto = request.form.get("foto", "").strip()

    if not nombre:
        flash("El nombre del actor es obligatorio.", "error")
        return redirect(url_for("agregar_actor"))

    if nacionalidad and not es_nacionalidad_valida(nacionalidad):
        flash(
            "La nacionalidad solo puede tener letras, espacios y guiones.",
            "error"
        )
        return redirect(url_for("agregar_actor"))

    fecha_nacimiento = None

    if fecha_texto:
        try:
            fecha = datetime.strptime(fecha_texto, "%Y-%m-%d").date()
        except ValueError:
            flash("La fecha de nacimiento no es válida.", "error")
            return redirect(url_for("agregar_actor"))

        if fecha > date.today() or fecha.year < 1800:
            flash("La fecha de nacimiento no es válida.", "error")
            return redirect(url_for("agregar_actor"))

        fecha_nacimiento = fecha.isoformat()

    try:
        with closing(conectar_bd()) as conexion:
            existente = conexion.execute("""
                SELECT 1 FROM actores
                WHERE lower(nombre) = lower(?)
            """, (nombre,)).fetchone()

            if existente:
                flash("Ya existe un actor con ese nombre.", "error")
                return redirect(url_for("agregar_actor"))

            conexion.execute("""
                INSERT INTO actores (
                    nombre, fecha_nacimiento, nacionalidad,
                    biografia, foto
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                nombre, fecha_nacimiento, nacionalidad,
                biografia, foto
            ))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("Ya existe un actor con ese nombre.", "error")
        return redirect(url_for("agregar_actor"))

    flash("Actor registrado correctamente.", "exito")
    return redirect(url_for("catalogo_actores"))

@app.route("/actores/<int:id_actor>/editar", methods=["GET", "POST"])
@admin_requerido
def editar_actor(id_actor):
    with closing(conectar_bd()) as conexion:
        actor = conexion.execute("""
            SELECT * FROM actores WHERE id_actor = ?
        """, (id_actor,)).fetchone()

    if actor is None:
        flash("No se encontró ese actor.", "error")
        return redirect(url_for("catalogo_actores"))

    if request.method == "GET":
        return render_template("editar_actor.html", actor=actor)

    # ----- POST: guardar los cambios -----
    volver = url_for("editar_actor", id_actor=id_actor)

    nombre = request.form.get("nombre", "").strip()
    fecha_texto = request.form.get("fecha_nacimiento", "").strip()
    nacionalidad = request.form.get("nacionalidad", "").strip()
    biografia = request.form.get("biografia", "").strip()
    foto = request.form.get("foto", "").strip()

    if not nombre:
        flash("El nombre del actor es obligatorio.", "error")
        return redirect(volver)

    if nacionalidad and not es_nacionalidad_valida(nacionalidad):
        flash(
            "La nacionalidad solo puede tener letras, espacios y guiones.",
            "error"
        )
        return redirect(volver)

    fecha_nacimiento = None

    if fecha_texto:
        try:
            fecha = datetime.strptime(fecha_texto, "%Y-%m-%d").date()
        except ValueError:
            flash("La fecha de nacimiento no es válida.", "error")
            return redirect(volver)

        if fecha > date.today() or fecha.year < 1800:
            flash("La fecha de nacimiento no es válida.", "error")
            return redirect(volver)

        fecha_nacimiento = fecha.isoformat()

    try:
        with closing(conectar_bd()) as conexion:
            repetido = conexion.execute("""
                SELECT 1 FROM actores
                WHERE lower(nombre) = lower(?)
                  AND id_actor != ?
            """, (nombre, id_actor)).fetchone()

            if repetido:
                flash("Ya existe otro actor con ese nombre.", "error")
                return redirect(volver)

            conexion.execute("""
                UPDATE actores
                SET nombre = ?, fecha_nacimiento = ?,
                    nacionalidad = ?, biografia = ?, foto = ?
                WHERE id_actor = ?
            """, (
                nombre, fecha_nacimiento, nacionalidad,
                biografia, foto, id_actor
            ))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("Ya existe otro actor con ese nombre.", "error")
        return redirect(volver)

    flash("Actor actualizado correctamente.", "exito")
    return redirect(url_for("detalle_actor", id_actor=id_actor))


@app.route("/actores/<int:id_actor>/eliminar", methods=["POST"])
@admin_requerido
def eliminar_actor(id_actor):
    with closing(conectar_bd()) as conexion:
        actor = conexion.execute("""
            SELECT 1 FROM actores WHERE id_actor = ?
        """, (id_actor,)).fetchone()

        if actor is None:
            flash("No se encontró ese actor.", "error")
            return redirect(url_for("catalogo_actores"))

        en_reparto = conexion.execute("""
            SELECT
                (SELECT COUNT(*) FROM reparto_pelicula
                 WHERE id_actor = ?)
              + (SELECT COUNT(*) FROM reparto_serie
                 WHERE id_actor = ?)
        """, (id_actor, id_actor)).fetchone()[0]

        if en_reparto:
            flash(
                f"No se puede eliminar: aparece en {en_reparto} fila(s) "
                "de reparto. Quítalo primero del reparto de cada "
                "película o serie.",
                "error"
            )
            return redirect(url_for("detalle_actor", id_actor=id_actor))

        try:
            conexion.execute("""
                DELETE FROM actores WHERE id_actor = ?
            """, (id_actor,))
            conexion.commit()

        except sqlite3.IntegrityError:
            flash("No se pudo eliminar al actor.", "error")
            return redirect(url_for("detalle_actor", id_actor=id_actor))

    flash("Actor eliminado correctamente.", "exito")
    return redirect(url_for("catalogo_actores"))

@app.route("/actores/<int:id_actor>")
def detalle_actor(id_actor):
    with closing(conectar_bd()) as conexion:
        actor = conexion.execute("""
            SELECT * FROM actores WHERE id_actor = ?
        """, (id_actor,)).fetchone()

        if actor is None:
            flash("No se encontró ese actor.", "error")
            return redirect(url_for("catalogo_actores"))

        peliculas = conexion.execute("""
            SELECT p.titulo, p.anio_estreno,
                   per.nombre AS personaje
            FROM reparto_pelicula r
            JOIN peliculas p ON r.id_pelicula = p.id_pelicula
            JOIN personajes per ON r.id_personaje = per.id_personaje
            WHERE r.id_actor = ?
            ORDER BY p.anio_estreno, p.titulo
        """, (id_actor,)).fetchall()

        series = conexion.execute("""
            SELECT s.titulo, s.anio_inicio,
                   per.nombre AS personaje
            FROM reparto_serie r
            JOIN series s ON r.id_serie = s.id_serie
            JOIN personajes per ON r.id_personaje = per.id_personaje
            WHERE r.id_actor = ?
            ORDER BY s.anio_inicio, s.titulo
        """, (id_actor,)).fetchall()

        personajes = conexion.execute("""
            SELECT per.id_personaje, per.nombre
            FROM personajes per
            WHERE per.id_personaje IN (
                SELECT id_personaje FROM reparto_pelicula
                WHERE id_actor = ?
                UNION
                SELECT id_personaje FROM reparto_serie
                WHERE id_actor = ?
            )
            ORDER BY per.nombre
        """, (id_actor, id_actor)).fetchall()

    return render_template(
        "actor.html",
        actor=actor,
        peliculas=peliculas,
        series=series,
        personajes=personajes
    )

@app.route("/personajes")
def catalogo_personajes():
    with closing(conectar_bd()) as conexion:
        personajes = conexion.execute("""
            SELECT * FROM personajes ORDER BY nombre
        """).fetchall()

    return render_template("personajes.html", personajes=personajes)


@app.route("/personajes/agregar")
@admin_requerido
def agregar_personaje():
    return render_template("agregar_personaje.html")


@app.route("/personajes/nuevo", methods=["POST"])
@admin_requerido
def nuevo_personaje():
    nombre = request.form.get("nombre", "").strip()
    alias = request.form.get("alias", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    imagen = request.form.get("imagen", "").strip()

    if not nombre:
        flash("El nombre del personaje es obligatorio.", "error")
        return redirect(url_for("agregar_personaje"))

    if len(nombre) > 80 or len(alias) > 80:
        flash("El nombre y el alias pueden tener hasta 80 caracteres.", "error")
        return redirect(url_for("agregar_personaje"))

    try:
        with closing(conectar_bd()) as conexion:
            existente = conexion.execute("""
                SELECT 1 FROM personajes
                WHERE lower(nombre) = lower(?)
            """, (nombre,)).fetchone()

            if existente:
                flash("Ya existe un personaje con ese nombre.", "error")
                return redirect(url_for("agregar_personaje"))

            conexion.execute("""
                INSERT INTO personajes (
                    nombre, alias, descripcion, imagen
                )
                VALUES (?, ?, ?, ?)
            """, (nombre, alias, descripcion, imagen))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("Ya existe un personaje con ese nombre.", "error")
        return redirect(url_for("agregar_personaje"))

    flash("Personaje registrado correctamente.", "exito")
    return redirect(url_for("catalogo_personajes"))

@app.route(
    "/personajes/<int:id_personaje>/editar",
    methods=["GET", "POST"]
)
@admin_requerido
def editar_personaje(id_personaje):
    with closing(conectar_bd()) as conexion:
        personaje = conexion.execute("""
            SELECT * FROM personajes WHERE id_personaje = ?
        """, (id_personaje,)).fetchone()

    if personaje is None:
        flash("No se encontró ese personaje.", "error")
        return redirect(url_for("catalogo_personajes"))

    if request.method == "GET":
        return render_template("editar_personaje.html", personaje=personaje)

    # ----- POST: guardar los cambios -----
    volver = url_for("editar_personaje", id_personaje=id_personaje)

    nombre = request.form.get("nombre", "").strip()
    alias = request.form.get("alias", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    imagen = request.form.get("imagen", "").strip()

    if not nombre:
        flash("El nombre del personaje es obligatorio.", "error")
        return redirect(volver)

    if len(nombre) > 80 or len(alias) > 80:
        flash("El nombre y el alias pueden tener hasta 80 caracteres.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            repetido = conexion.execute("""
                SELECT 1 FROM personajes
                WHERE lower(nombre) = lower(?)
                  AND id_personaje != ?
            """, (nombre, id_personaje)).fetchone()

            if repetido:
                flash("Ya existe otro personaje con ese nombre.", "error")
                return redirect(volver)

            conexion.execute("""
                UPDATE personajes
                SET nombre = ?, alias = ?,
                    descripcion = ?, imagen = ?
                WHERE id_personaje = ?
            """, (nombre, alias, descripcion, imagen, id_personaje))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("Ya existe otro personaje con ese nombre.", "error")
        return redirect(volver)

    flash("Personaje actualizado correctamente.", "exito")
    return redirect(url_for("detalle_personaje", id_personaje=id_personaje))


@app.route("/personajes/<int:id_personaje>/eliminar", methods=["POST"])
@admin_requerido
def eliminar_personaje(id_personaje):
    with closing(conectar_bd()) as conexion:
        personaje = conexion.execute("""
            SELECT 1 FROM personajes WHERE id_personaje = ?
        """, (id_personaje,)).fetchone()

        if personaje is None:
            flash("No se encontró ese personaje.", "error")
            return redirect(url_for("catalogo_personajes"))

        en_reparto = conexion.execute("""
            SELECT
                (SELECT COUNT(*) FROM reparto_pelicula
                 WHERE id_personaje = ?)
              + (SELECT COUNT(*) FROM reparto_serie
                 WHERE id_personaje = ?)
        """, (id_personaje, id_personaje)).fetchone()[0]

        if en_reparto:
            flash(
                f"No se puede eliminar: aparece en {en_reparto} fila(s) "
                "de reparto. Quítalo primero del reparto de cada "
                "película o serie.",
                "error"
            )
            return redirect(
                url_for("detalle_personaje", id_personaje=id_personaje)
            )

        try:
            conexion.execute("""
                DELETE FROM personajes WHERE id_personaje = ?
            """, (id_personaje,))
            conexion.commit()

        except sqlite3.IntegrityError:
            flash("No se pudo eliminar al personaje.", "error")
            return redirect(
                url_for("detalle_personaje", id_personaje=id_personaje)
            )

    flash("Personaje eliminado correctamente.", "exito")
    return redirect(url_for("catalogo_personajes"))

@app.route("/personajes/<int:id_personaje>")
def detalle_personaje(id_personaje):
    with closing(conectar_bd()) as conexion:
        personaje = conexion.execute("""
            SELECT * FROM personajes WHERE id_personaje = ?
        """, (id_personaje,)).fetchone()

        if personaje is None:
            flash("No se encontró ese personaje.", "error")
            return redirect(url_for("catalogo_personajes"))

        universos = conexion.execute("""
            SELECT u.nombre
            FROM universos u
            WHERE u.id_universo IN (
                SELECT p.id_universo
                FROM reparto_pelicula r
                JOIN peliculas p ON r.id_pelicula = p.id_pelicula
                WHERE r.id_personaje = ?
                UNION
                SELECT s.id_universo
                FROM reparto_serie r
                JOIN series s ON r.id_serie = s.id_serie
                WHERE r.id_personaje = ?
            )
            ORDER BY u.nombre
        """, (id_personaje, id_personaje)).fetchall()

        actores = conexion.execute("""
            SELECT a.id_actor, a.nombre
            FROM actores a
            WHERE a.id_actor IN (
                SELECT id_actor FROM reparto_pelicula
                WHERE id_personaje = ?
                UNION
                SELECT id_actor FROM reparto_serie
                WHERE id_personaje = ?
            )
            ORDER BY a.nombre
        """, (id_personaje, id_personaje)).fetchall()

        peliculas = conexion.execute("""
            SELECT p.titulo, p.anio_estreno,
                   a.id_actor, a.nombre AS actor
            FROM reparto_pelicula r
            JOIN peliculas p ON r.id_pelicula = p.id_pelicula
            JOIN actores a ON r.id_actor = a.id_actor
            WHERE r.id_personaje = ?
            ORDER BY p.anio_estreno, p.titulo
        """, (id_personaje,)).fetchall()

        series = conexion.execute("""
            SELECT s.titulo, s.anio_inicio,
                   a.id_actor, a.nombre AS actor
            FROM reparto_serie r
            JOIN series s ON r.id_serie = s.id_serie
            JOIN actores a ON r.id_actor = a.id_actor
            WHERE r.id_personaje = ?
            ORDER BY s.anio_inicio, s.titulo
        """, (id_personaje,)).fetchall()

    return render_template(
        "personaje.html",
        personaje=personaje,
        universos=universos,
        actores=actores,
        peliculas=peliculas,
        series=series
    )

@app.route(
    "/propuestas-pelicula/<int:id_propuesta>/aprobar",
    methods=["POST"]
)
@admin_requerido
def aprobar_propuesta_pelicula(id_propuesta):
    with closing(conectar_bd()) as conexion:
        propuesta = conexion.execute("""
            SELECT * FROM propuestas_pelicula
            WHERE id_propuesta = ?
        """, (id_propuesta,)).fetchone()

        if propuesta is None:
            flash("No se encontró esa propuesta.", "error")
            return redirect(url_for("solicitudes"))

        if propuesta["estado"] != "pendiente":
            flash("Esa propuesta ya fue revisada.", "error")
            return redirect(url_for("solicitudes"))

        # Volver a validar: el universo o la fase pudieron cambiar
        universo = conexion.execute("""
            SELECT id_universo FROM universos
            WHERE id_universo = ?
        """, (propuesta["id_universo"],)).fetchone()

        if universo is None:
            flash(
                "El universo propuesto ya no existe. "
                "Rechaza la propuesta.",
                "error"
            )
            return redirect(url_for("solicitudes"))

        if propuesta["id_fase"] is not None:
            fase = conexion.execute("""
                SELECT id_universo FROM fases
                WHERE id_fase = ?
            """, (propuesta["id_fase"],)).fetchone()

            if fase is None or fase["id_universo"] != propuesta["id_universo"]:
                flash(
                    "La fase propuesta ya no es válida para ese universo. "
                    "Rechaza la propuesta.",
                    "error"
                )
                return redirect(url_for("solicitudes"))

        existente = conexion.execute("""
            SELECT 1 FROM peliculas
            WHERE lower(titulo) = lower(?)
              AND anio_estreno IS ?
        """, (propuesta["titulo"], propuesta["anio_estreno"])).fetchone()

        if existente:
            flash(
                "Ya existe una película con ese título y año. "
                "Rechaza la propuesta.",
                "error"
            )
            return redirect(url_for("solicitudes"))

        try:
            conexion.execute("""
                INSERT INTO peliculas (
                    titulo, anio_estreno, duracion_minutos,
                    sinopsis, portada, trailer_url,
                    id_fase, id_universo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                propuesta["titulo"], propuesta["anio_estreno"],
                propuesta["duracion_minutos"], propuesta["sinopsis"],
                propuesta["portada"], propuesta["trailer_url"],
                propuesta["id_fase"], propuesta["id_universo"]
            ))

            resultado = conexion.execute("""
                UPDATE propuestas_pelicula
                SET estado = 'aprobada',
                    id_admin_revisor = ?,
                    fecha_revision = datetime('now')
                WHERE id_propuesta = ?
                  AND estado = 'pendiente'
            """, (session["id_usuario"], id_propuesta))

            if resultado.rowcount == 0:
                conexion.rollback()
                flash("Esa propuesta ya fue revisada.", "error")
                return redirect(url_for("solicitudes"))

            conexion.commit()

        except sqlite3.IntegrityError:
            conexion.rollback()
            flash("No se pudo crear la película.", "error")
            return redirect(url_for("solicitudes"))

    flash("Propuesta aprobada: la película fue creada.", "exito")
    return redirect(url_for("solicitudes"))


@app.route(
    "/propuestas-pelicula/<int:id_propuesta>/rechazar",
    methods=["POST"]
)
@admin_requerido
def rechazar_propuesta_pelicula(id_propuesta):
    motivo = request.form.get("motivo", "").strip()

    if not 3 <= len(motivo) <= 300:
        flash(
            "Escribe el motivo del rechazo (entre 3 y 300 caracteres).",
            "error"
        )
        return redirect(url_for("solicitudes"))

    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            UPDATE propuestas_pelicula
            SET estado = 'rechazada',
                motivo_rechazo = ?,
                id_admin_revisor = ?,
                fecha_revision = datetime('now')
            WHERE id_propuesta = ?
              AND estado = 'pendiente'
        """, (motivo, session["id_usuario"], id_propuesta))

        if resultado.rowcount == 0:
            flash("Esa propuesta no existe o ya fue revisada.", "error")
        else:
            conexion.commit()
            flash("Propuesta rechazada. No se creó la película.", "exito")

    return redirect(url_for("solicitudes"))


@app.route(
    "/propuestas-serie/<int:id_propuesta>/aprobar",
    methods=["POST"]
)
@admin_requerido
def aprobar_propuesta_serie(id_propuesta):
    with closing(conectar_bd()) as conexion:
        propuesta = conexion.execute("""
            SELECT * FROM propuestas_serie
            WHERE id_propuesta = ?
        """, (id_propuesta,)).fetchone()

        if propuesta is None:
            flash("No se encontró esa propuesta.", "error")
            return redirect(url_for("solicitudes"))

        if propuesta["estado"] != "pendiente":
            flash("Esa propuesta ya fue revisada.", "error")
            return redirect(url_for("solicitudes"))

        universo = conexion.execute("""
            SELECT id_universo FROM universos
            WHERE id_universo = ?
        """, (propuesta["id_universo"],)).fetchone()

        if universo is None:
            flash(
                "El universo propuesto ya no existe. "
                "Rechaza la propuesta.",
                "error"
            )
            return redirect(url_for("solicitudes"))

        if propuesta["id_fase"] is not None:
            fase = conexion.execute("""
                SELECT id_universo FROM fases
                WHERE id_fase = ?
            """, (propuesta["id_fase"],)).fetchone()

            if fase is None or fase["id_universo"] != propuesta["id_universo"]:
                flash(
                    "La fase propuesta ya no es válida para ese universo. "
                    "Rechaza la propuesta.",
                    "error"
                )
                return redirect(url_for("solicitudes"))

        existente = conexion.execute("""
            SELECT 1 FROM series
            WHERE lower(titulo) = lower(?)
              AND anio_inicio IS ?
        """, (propuesta["titulo"], propuesta["anio_inicio"])).fetchone()

        if existente:
            flash(
                "Ya existe una serie con ese título y año. "
                "Rechaza la propuesta.",
                "error"
            )
            return redirect(url_for("solicitudes"))

        try:
            conexion.execute("""
                INSERT INTO series (
                    titulo, anio_inicio, temporadas,
                    sinopsis, portada, trailer_url,
                    id_fase, id_universo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                propuesta["titulo"], propuesta["anio_inicio"],
                propuesta["temporadas"], propuesta["sinopsis"],
                propuesta["portada"], propuesta["trailer_url"],
                propuesta["id_fase"], propuesta["id_universo"]
            ))

            resultado = conexion.execute("""
                UPDATE propuestas_serie
                SET estado = 'aprobada',
                    id_admin_revisor = ?,
                    fecha_revision = datetime('now')
                WHERE id_propuesta = ?
                  AND estado = 'pendiente'
            """, (session["id_usuario"], id_propuesta))

            if resultado.rowcount == 0:
                conexion.rollback()
                flash("Esa propuesta ya fue revisada.", "error")
                return redirect(url_for("solicitudes"))

            conexion.commit()

        except sqlite3.IntegrityError:
            conexion.rollback()
            flash("No se pudo crear la serie.", "error")
            return redirect(url_for("solicitudes"))

    flash("Propuesta aprobada: la serie fue creada.", "exito")
    return redirect(url_for("solicitudes"))


@app.route(
    "/propuestas-serie/<int:id_propuesta>/rechazar",
    methods=["POST"]
)
@admin_requerido
def rechazar_propuesta_serie(id_propuesta):
    motivo = request.form.get("motivo", "").strip()

    if not 3 <= len(motivo) <= 300:
        flash(
            "Escribe el motivo del rechazo (entre 3 y 300 caracteres).",
            "error"
        )
        return redirect(url_for("solicitudes"))

    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            UPDATE propuestas_serie
            SET estado = 'rechazada',
                motivo_rechazo = ?,
                id_admin_revisor = ?,
                fecha_revision = datetime('now')
            WHERE id_propuesta = ?
              AND estado = 'pendiente'
        """, (motivo, session["id_usuario"], id_propuesta))

        if resultado.rowcount == 0:
            flash("Esa propuesta no existe o ya fue revisada.", "error")
        else:
            conexion.commit()
            flash("Propuesta rechazada. No se creó la serie.", "exito")

    return redirect(url_for("solicitudes"))

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "exito")
    return redirect(url_for("inicio"))

@app.route("/")
def inicio():
    with closing(conectar_bd()) as conexion:
        peliculas = conexion.execute("""
            SELECT p.*, u.nombre AS universo
            FROM peliculas p
            LEFT JOIN universos u
                ON p.id_universo = u.id_universo
            ORDER BY p.id_pelicula DESC
            LIMIT 10
        """).fetchall()

        series = conexion.execute("""
            SELECT s.*, u.nombre AS universo
            FROM series s
            LEFT JOIN universos u
                ON s.id_universo = u.id_universo
            ORDER BY s.id_serie DESC
            LIMIT 10
        """).fetchall()

    return render_template(
        "index.html",
        peliculas=peliculas,
        series=series
    )

ORDENES_PELICULAS = {
    "titulo": "p.titulo COLLATE NOCASE",
    "anio_asc": "p.anio_estreno IS NULL, p.anio_estreno ASC, "
                "p.titulo COLLATE NOCASE",
    "anio_desc": "p.anio_estreno IS NULL, p.anio_estreno DESC, "
                 "p.titulo COLLATE NOCASE",
}


@app.route("/peliculas")
def catalogo_peliculas():
    orden = request.args.get("orden", "titulo")

    if orden not in ORDENES_PELICULAS:
        orden = "titulo"

    with closing(conectar_bd()) as conexion:
        peliculas = conexion.execute(f"""
            SELECT p.*, f.nombre AS fase,
                   u.nombre AS universo
            FROM peliculas p
            LEFT JOIN fases f ON p.id_fase = f.id_fase
            LEFT JOIN universos u
                ON p.id_universo = u.id_universo
            ORDER BY {ORDENES_PELICULAS[orden]}
        """).fetchall()

        universos = conexion.execute("""
            SELECT * FROM universos ORDER BY nombre
        """).fetchall()

        fases = conexion.execute("""
            SELECT f.id_fase, f.nombre, f.numero,
                   f.id_universo, u.nombre AS universo
            FROM fases f
            JOIN universos u
                ON f.id_universo = u.id_universo
            ORDER BY u.nombre, f.numero
        """).fetchall()

    return render_template(
        "peliculas.html",
        peliculas=peliculas,
        universos=universos,
        fases=fases,
        orden=orden
    )

@app.route("/peliculas/<int:id_pelicula>")
def detalle_pelicula(id_pelicula):
    with closing(conectar_bd()) as conexion:
        pelicula = conexion.execute("""
            SELECT p.*, f.nombre AS fase, u.nombre AS universo
            FROM peliculas p
            LEFT JOIN fases f ON p.id_fase = f.id_fase
            LEFT JOIN universos u ON p.id_universo = u.id_universo
            WHERE p.id_pelicula = ?
        """, (id_pelicula,)).fetchone()

        if pelicula is None:
            flash("No se encontró esa película.", "error")
            return redirect(url_for("catalogo_peliculas"))

        reparto = conexion.execute("""
            SELECT r.id_reparto,
                   a.id_actor, a.nombre AS actor,
                   per.id_personaje, per.nombre AS personaje
            FROM reparto_pelicula r
            JOIN actores a ON r.id_actor = a.id_actor
            JOIN personajes per ON r.id_personaje = per.id_personaje
            WHERE r.id_pelicula = ?
            ORDER BY per.nombre, a.nombre
        """, (id_pelicula,)).fetchall()

        resumen = conexion.execute("""
            SELECT COUNT(*) AS total, AVG(puntuacion) AS promedio
            FROM valoraciones_pelicula
            WHERE id_pelicula = ?
        """, (id_pelicula,)).fetchone()

        valoraciones = conexion.execute("""
            SELECT v.id_valoracion, v.id_usuario, v.puntuacion,
                   v.comentario, v.fecha, v.fecha_edicion,
                   u.nombre_usuario AS usuario
            FROM valoraciones_pelicula v
            JOIN usuarios u ON v.id_usuario = u.id_usuario
            WHERE v.id_pelicula = ?
            ORDER BY v.fecha DESC
        """, (id_pelicula,)).fetchall()

        mi_valoracion = None

        if session.get("id_usuario"):
            mi_valoracion = conexion.execute("""
                SELECT puntuacion, comentario
                FROM valoraciones_pelicula
                WHERE id_pelicula = ? AND id_usuario = ?
            """, (id_pelicula, session["id_usuario"])).fetchone()

        actores = []
        personajes = []

        if session.get("rol") == "admin":
            actores = conexion.execute("""
                SELECT id_actor, nombre FROM actores ORDER BY nombre
            """).fetchall()

            personajes = conexion.execute("""
                SELECT id_personaje, nombre FROM personajes ORDER BY nombre
            """).fetchall()

    return render_template(
        "detalle_pelicula.html",
        pelicula=pelicula,
        reparto=reparto,
        actores=actores,
        personajes=personajes,
        resumen=resumen,
        valoraciones=valoraciones,
        mi_valoracion=mi_valoracion
    )


@app.route(
    "/peliculas/<int:id_pelicula>/reparto/agregar",
    methods=["POST"]
)
@admin_requerido
def agregar_reparto_pelicula(id_pelicula):
    volver = url_for("detalle_pelicula", id_pelicula=id_pelicula)

    actor_texto = request.form.get("id_actor", "").strip()
    personaje_texto = request.form.get("id_personaje", "").strip()

    try:
        id_actor = int(actor_texto)
        id_personaje = int(personaje_texto)

        if id_actor < 1 or id_personaje < 1:
            raise ValueError

    except ValueError:
        flash("Selecciona un actor y un personaje.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            pelicula = conexion.execute("""
                SELECT 1 FROM peliculas WHERE id_pelicula = ?
            """, (id_pelicula,)).fetchone()

            if pelicula is None:
                flash("No se encontró esa película.", "error")
                return redirect(url_for("catalogo_peliculas"))

            actor = conexion.execute("""
                SELECT 1 FROM actores WHERE id_actor = ?
            """, (id_actor,)).fetchone()

            if actor is None:
                flash("El actor seleccionado no existe.", "error")
                return redirect(volver)

            personaje = conexion.execute("""
                SELECT 1 FROM personajes WHERE id_personaje = ?
            """, (id_personaje,)).fetchone()

            if personaje is None:
                flash("El personaje seleccionado no existe.", "error")
                return redirect(volver)

            existente = conexion.execute("""
                SELECT 1 FROM reparto_pelicula
                WHERE id_pelicula = ?
                  AND id_actor = ?
                  AND id_personaje = ?
            """, (id_pelicula, id_actor, id_personaje)).fetchone()

            if existente:
                flash("Ese actor ya interpreta a ese personaje aquí.", "error")
                return redirect(volver)

            conexion.execute("""
                INSERT INTO reparto_pelicula (
                    id_pelicula, id_actor, id_personaje
                )
                VALUES (?, ?, ?)
            """, (id_pelicula, id_actor, id_personaje))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo agregar al reparto.", "error")
        return redirect(volver)

    flash("Reparto actualizado correctamente.", "exito")
    return redirect(volver)


@app.route(
    "/peliculas/<int:id_pelicula>/reparto/<int:id_reparto>/quitar",
    methods=["POST"]
)
@admin_requerido
def quitar_reparto_pelicula(id_pelicula, id_reparto):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM reparto_pelicula
            WHERE id_reparto = ?
              AND id_pelicula = ?
        """, (id_reparto, id_pelicula))

        if resultado.rowcount == 0:
            flash("No se encontró esa fila del reparto.", "error")
        else:
            conexion.commit()
            flash("Quitado del reparto.", "exito")

    return redirect(url_for("detalle_pelicula", id_pelicula=id_pelicula))

@app.route("/peliculas/proponer-nueva", methods=["GET", "POST"])
@login_requerido
def proponer_pelicula_nueva():
    if session.get("rol") == "admin":
        flash(
            "Los administradores registran las películas directamente.",
            "error"
        )
        return redirect(url_for("agregar_pelicula"))

    if request.method == "GET":
        with closing(conectar_bd()) as conexion:
            universos = conexion.execute("""
                SELECT * FROM universos ORDER BY nombre
            """).fetchall()

            fases = conexion.execute("""
                SELECT f.id_fase, f.nombre, f.numero,
                       f.id_universo, u.nombre AS universo
                FROM fases f
                JOIN universos u
                    ON f.id_universo = u.id_universo
                ORDER BY u.nombre, f.numero
            """).fetchall()

        return render_template(
            "proponer_pelicula.html",
            universos=universos,
            fases=fases
        )

    # ----- POST: guardar la propuesta -----
    volver = url_for("proponer_pelicula_nueva")

    titulo = request.form.get("titulo", "").strip()
    anio_texto = request.form.get("anio", "").strip()
    duracion_texto = request.form.get("duracion", "").strip()
    sinopsis = request.form.get("sinopsis", "").strip()
    portada = request.form.get("portada", "").strip()
    trailer = request.form.get("trailer", "").strip()
    fase_texto = request.form.get("id_fase", "").strip()
    universo_texto = request.form.get("id_universo", "").strip()

    if not titulo:
        flash("El título de la película es obligatorio.", "error")
        return redirect(volver)

    if not universo_texto:
        flash("Selecciona el universo de la película.", "error")
        return redirect(volver)

    try:
        anio = int(anio_texto) if anio_texto else None
        duracion = int(duracion_texto) if duracion_texto else None
        id_fase = int(fase_texto) if fase_texto else None
        id_universo = int(universo_texto)

        if anio is not None and not 1888 <= anio <= 2100:
            raise ValueError

        if duracion is not None and duracion < 1:
            raise ValueError

        if id_fase is not None and id_fase < 1:
            raise ValueError

        if id_universo < 1:
            raise ValueError

    except ValueError:
        flash("Revisa el año, la duración, la fase y el universo.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            universo = conexion.execute("""
                SELECT id_universo FROM universos
                WHERE id_universo = ?
            """, (id_universo,)).fetchone()

            if universo is None:
                flash("El universo seleccionado no existe.", "error")
                return redirect(volver)

            if id_fase is not None:
                fase = conexion.execute("""
                    SELECT id_universo FROM fases
                    WHERE id_fase = ?
                """, (id_fase,)).fetchone()

                if fase is None:
                    flash("La fase seleccionada no existe.", "error")
                    return redirect(volver)

                if fase["id_universo"] != id_universo:
                    flash(
                        "La fase seleccionada no pertenece "
                        "al universo elegido.",
                        "error"
                    )
                    return redirect(volver)

            existente = conexion.execute("""
                SELECT 1 FROM peliculas
                WHERE lower(titulo) = lower(?)
                  AND anio_estreno IS ?
            """, (titulo, anio)).fetchone()

            if existente:
                flash(
                    "Ya existe una película con ese título y año.",
                    "error"
                )
                return redirect(volver)

            pendiente = conexion.execute("""
                SELECT 1 FROM propuestas_pelicula
                WHERE id_usuario = ?
                  AND lower(titulo) = lower(?)
                  AND estado = 'pendiente'
            """, (session["id_usuario"], titulo)).fetchone()

            if pendiente:
                flash(
                    "Ya tienes una propuesta pendiente con ese título.",
                    "error"
                )
                return redirect(url_for("catalogo_peliculas"))

            conexion.execute("""
                INSERT INTO propuestas_pelicula (
                    id_usuario, titulo, anio_estreno,
                    duracion_minutos, sinopsis, portada,
                    trailer_url, id_fase, id_universo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session["id_usuario"], titulo, anio,
                duracion, sinopsis, portada,
                trailer, id_fase, id_universo
            ))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo enviar la propuesta.", "error")
        return redirect(volver)

    flash(
        "Tu propuesta fue enviada. Un administrador la revisará.",
        "exito"
    )
    return redirect(url_for("catalogo_peliculas"))

@app.route("/peliculas/<int:id_pelicula>/valorar", methods=["POST"])
@login_requerido
def valorar_pelicula(id_pelicula):
    volver = url_for("detalle_pelicula", id_pelicula=id_pelicula)

    puntuacion_texto = request.form.get("puntuacion", "").strip()
    comentario = request.form.get("comentario", "").strip()

    try:
        puntuacion = int(puntuacion_texto)
    except ValueError:
        puntuacion = 0

    if not 1 <= puntuacion <= 5:
        flash("Elige una calificación de 1 a 5.", "error")
        return redirect(volver)

    if len(comentario) > 500:
        flash("El comentario puede tener hasta 500 caracteres.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            pelicula = conexion.execute("""
                SELECT 1 FROM peliculas WHERE id_pelicula = ?
            """, (id_pelicula,)).fetchone()

            if pelicula is None:
                flash("No se encontró esa película.", "error")
                return redirect(url_for("catalogo_peliculas"))

            conexion.execute("""
                INSERT INTO valoraciones_pelicula (
                    id_usuario, id_pelicula, puntuacion, comentario
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT (id_usuario, id_pelicula) DO UPDATE SET
                    puntuacion = excluded.puntuacion,
                    comentario = excluded.comentario,
                    fecha_edicion = datetime('now')
            """, (session["id_usuario"], id_pelicula, puntuacion, comentario))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo guardar tu calificación.", "error")
        return redirect(volver)

    flash("Tu calificación fue guardada.", "exito")
    return redirect(volver)


@app.route(
    "/peliculas/<int:id_pelicula>/valoraciones/<int:id_valoracion>/eliminar",
    methods=["POST"]
)
@login_requerido
def eliminar_valoracion_pelicula(id_pelicula, id_valoracion):
    es_admin = 1 if session.get("rol") == "admin" else 0

    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM valoraciones_pelicula
            WHERE id_valoracion = ?
              AND id_pelicula = ?
              AND (id_usuario = ? OR ? = 1)
        """, (id_valoracion, id_pelicula, session["id_usuario"], es_admin))

        if resultado.rowcount == 0:
            flash(
                "No se pudo borrar: no existe o no es tuya.",
                "error"
            )
        else:
            conexion.commit()
            flash("Calificación eliminada.", "exito")

    return redirect(url_for("detalle_pelicula", id_pelicula=id_pelicula))

@app.route("/peliculas/agregar")
@admin_requerido
def agregar_pelicula():
    with closing(conectar_bd()) as conexion:
        universos = conexion.execute("""
            SELECT * FROM universos ORDER BY nombre
        """).fetchall()

        fases = conexion.execute("""
            SELECT f.id_fase, f.nombre, f.numero,
                   f.id_universo, u.nombre AS universo
            FROM fases f
            JOIN universos u
                ON f.id_universo = u.id_universo
            ORDER BY u.nombre, f.numero
        """).fetchall()

    return render_template(
        "agregar_pelicula.html",
        universos=universos,
        fases=fases
    )

@app.route("/universos")
@admin_requerido
def universos_fases():
    with closing(conectar_bd()) as conexion:
        universos = conexion.execute("""
            SELECT * FROM universos ORDER BY nombre
        """).fetchall()

        fases = conexion.execute("""
            SELECT f.id_fase, f.nombre, f.numero,
                   f.id_universo, u.nombre AS universo
            FROM fases f
            JOIN universos u
                ON f.id_universo = u.id_universo
            ORDER BY u.nombre, f.numero
        """).fetchall()

    return render_template(
        "universos_fases.html",
        universos=universos,
        fases=fases
    )

@app.route("/universos/nuevo", methods=["POST"])
@admin_requerido
def nuevo_universo():
    nombre = request.form.get("nombre", "").strip()
    descripcion = request.form.get("descripcion", "").strip()

    if not nombre:
        flash("Escribe el nombre del universo.", "error")
        return redirect(url_for("universos_fases"))

    try:
        with closing(conectar_bd()) as conexion:
            conexion.execute("""
                INSERT INTO universos (nombre, descripcion)
                VALUES (?, ?)
            """, (nombre, descripcion))
            conexion.commit()

        flash("Universo registrado correctamente.", "exito")

    except sqlite3.IntegrityError:
        flash("Ya existe un universo con ese nombre.", "error")

    return redirect(url_for("universos_fases"))


@app.route("/fases/nueva", methods=["POST"])
@admin_requerido
def nueva_fase():
    nombre = request.form.get("nombre", "").strip()
    numero_texto = request.form.get("numero", "").strip()
    id_universo = request.form.get("id_universo", "").strip()

    if not nombre or not numero_texto or not id_universo:
        flash("Completa todos los campos de la fase.", "error")
        return redirect(url_for("universos_fases"))

    try:
        numero = int(numero_texto)
        universo_id = int(id_universo)

        if numero < 1 or universo_id < 1:
            raise ValueError

        with closing(conectar_bd()) as conexion:
            conexion.execute("""
                INSERT INTO fases (nombre, numero, id_universo)
                VALUES (?, ?, ?)
            """, (nombre, numero, universo_id))
            conexion.commit()

        flash("Fase registrada correctamente.", "exito")

    except ValueError:
        flash("El número de fase y el universo deben ser válidos.", "error")

    except sqlite3.IntegrityError:
        flash("Fase duplicada o universo inexistente.", "error")

    return redirect(url_for("universos_fases"))


@app.route("/peliculas/nueva", methods=["POST"])
@admin_requerido
def nueva_pelicula():
    titulo = request.form.get("titulo", "").strip()
    anio_texto = request.form.get("anio", "").strip()
    duracion_texto = request.form.get("duracion", "").strip()
    sinopsis = request.form.get("sinopsis", "").strip()
    portada = request.form.get("portada", "").strip()
    trailer = request.form.get("trailer", "").strip()
    fase_texto = request.form.get("id_fase", "").strip()
    universo_texto = request.form.get("id_universo", "").strip()

    if not titulo:
        flash("El título de la película es obligatorio.", "error")
        return redirect(url_for("agregar_pelicula"))

    if not universo_texto:
        flash("Selecciona el universo de la película.", "error")
        return redirect(url_for("agregar_pelicula"))

    try:
        anio = int(anio_texto) if anio_texto else None
        duracion = int(duracion_texto) if duracion_texto else None
        id_fase = int(fase_texto) if fase_texto else None
        id_universo = int(universo_texto)

        if anio is not None and not 1888 <= anio <= 2100:
            raise ValueError

        if duracion is not None and duracion < 1:
            raise ValueError

        if id_fase is not None and id_fase < 1:
            raise ValueError

        if id_universo < 1:
            raise ValueError

        with closing(conectar_bd()) as conexion:
            # 1. Validar que el universo exista
            universo = conexion.execute("""
                SELECT id_universo
                FROM universos
                WHERE id_universo = ?
            """, (id_universo,)).fetchone()

            if universo is None:
                flash("El universo seleccionado no existe.", "error")
                return redirect(url_for("agregar_pelicula"))

            # 2. Si eligió fase, validar que exista y que sea de ese universo
            if id_fase is not None:
                fase = conexion.execute("""
                    SELECT id_universo
                    FROM fases
                    WHERE id_fase = ?
                """, (id_fase,)).fetchone()

                if fase is None:
                    flash("La fase seleccionada no existe.", "error")
                    return redirect(url_for("agregar_pelicula"))

                if fase["id_universo"] != id_universo:
                    flash(
                        "La fase seleccionada no pertenece "
                        "al universo elegido.",
                        "error"
                    )
                    return redirect(url_for("agregar_pelicula"))

            # 3. Guardar la película con su universo
            conexion.execute("""
                INSERT INTO peliculas (
                    titulo, anio_estreno, duracion_minutos,
                    sinopsis, portada, trailer_url,
                    id_fase, id_universo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                titulo, anio, duracion, sinopsis,
                portada, trailer, id_fase, id_universo
            ))
            conexion.commit()

        flash("Película registrada correctamente.", "exito")

    except ValueError:
        flash("Revisa el año, la duración, la fase y el universo.", "error")

    except sqlite3.IntegrityError:
        flash("No se pudo registrar: universo o fase inexistente.", "error")

    return redirect(url_for("agregar_pelicula"))

ORDENES_SERIES = {
    "titulo": "s.titulo COLLATE NOCASE",
    "anio_asc": "s.anio_inicio IS NULL, s.anio_inicio ASC, "
                "s.titulo COLLATE NOCASE",
    "anio_desc": "s.anio_inicio IS NULL, s.anio_inicio DESC, "
                 "s.titulo COLLATE NOCASE",
}


@app.route("/series")
def catalogo_series():
    orden = request.args.get("orden", "titulo")

    if orden not in ORDENES_SERIES:
        orden = "titulo"

    with closing(conectar_bd()) as conexion:
        series = conexion.execute(f"""
            SELECT s.*, f.nombre AS fase,
                   u.nombre AS universo
            FROM series s
            LEFT JOIN fases f ON s.id_fase = f.id_fase
            LEFT JOIN universos u
                ON s.id_universo = u.id_universo
            ORDER BY {ORDENES_SERIES[orden]}
        """).fetchall()

        universos = conexion.execute("""
            SELECT * FROM universos ORDER BY nombre
        """).fetchall()

    return render_template(
        "series.html",
        series=series,
        universos=universos,
        orden=orden
    )

@app.route("/series/<int:id_serie>")
def detalle_serie(id_serie):
    with closing(conectar_bd()) as conexion:
        serie = conexion.execute("""
            SELECT s.*, f.nombre AS fase, u.nombre AS universo
            FROM series s
            LEFT JOIN fases f ON s.id_fase = f.id_fase
            LEFT JOIN universos u ON s.id_universo = u.id_universo
            WHERE s.id_serie = ?
        """, (id_serie,)).fetchone()

        if serie is None:
            flash("No se encontró esa serie.", "error")
            return redirect(url_for("catalogo_series"))

        reparto = conexion.execute("""
            SELECT r.id_reparto,
                   a.id_actor, a.nombre AS actor,
                   per.id_personaje, per.nombre AS personaje
            FROM reparto_serie r
            JOIN actores a ON r.id_actor = a.id_actor
            JOIN personajes per ON r.id_personaje = per.id_personaje
            WHERE r.id_serie = ?
            ORDER BY per.nombre, a.nombre
        """, (id_serie,)).fetchall()

        resumen = conexion.execute("""
            SELECT COUNT(*) AS total, AVG(puntuacion) AS promedio
            FROM valoraciones_serie
            WHERE id_serie = ?
        """, (id_serie,)).fetchone()

        valoraciones = conexion.execute("""
            SELECT v.id_valoracion, v.id_usuario, v.puntuacion,
                   v.comentario, v.fecha, v.fecha_edicion,
                   u.nombre_usuario AS usuario
            FROM valoraciones_serie v
            JOIN usuarios u ON v.id_usuario = u.id_usuario
            WHERE v.id_serie = ?
            ORDER BY v.fecha DESC
        """, (id_serie,)).fetchall()

        mi_valoracion = None

        if session.get("id_usuario"):
            mi_valoracion = conexion.execute("""
                SELECT puntuacion, comentario
                FROM valoraciones_serie
                WHERE id_serie = ? AND id_usuario = ?
            """, (id_serie, session["id_usuario"])).fetchone()

        actores = []
        personajes = []

        if session.get("rol") == "admin":
            actores = conexion.execute("""
                SELECT id_actor, nombre FROM actores ORDER BY nombre
            """).fetchall()

            personajes = conexion.execute("""
                SELECT id_personaje, nombre FROM personajes ORDER BY nombre
            """).fetchall()

    return render_template(
        "detalle_serie.html",
        serie=serie,
        reparto=reparto,
        actores=actores,
        personajes=personajes,
        resumen=resumen,
        valoraciones=valoraciones,
        mi_valoracion=mi_valoracion
    )


@app.route(
    "/series/<int:id_serie>/reparto/agregar",
    methods=["POST"]
)
@admin_requerido
def agregar_reparto_serie(id_serie):
    volver = url_for("detalle_serie", id_serie=id_serie)

    actor_texto = request.form.get("id_actor", "").strip()
    personaje_texto = request.form.get("id_personaje", "").strip()

    try:
        id_actor = int(actor_texto)
        id_personaje = int(personaje_texto)

        if id_actor < 1 or id_personaje < 1:
            raise ValueError

    except ValueError:
        flash("Selecciona un actor y un personaje.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            serie = conexion.execute("""
                SELECT 1 FROM series WHERE id_serie = ?
            """, (id_serie,)).fetchone()

            if serie is None:
                flash("No se encontró esa serie.", "error")
                return redirect(url_for("catalogo_series"))

            actor = conexion.execute("""
                SELECT 1 FROM actores WHERE id_actor = ?
            """, (id_actor,)).fetchone()

            if actor is None:
                flash("El actor seleccionado no existe.", "error")
                return redirect(volver)

            personaje = conexion.execute("""
                SELECT 1 FROM personajes WHERE id_personaje = ?
            """, (id_personaje,)).fetchone()

            if personaje is None:
                flash("El personaje seleccionado no existe.", "error")
                return redirect(volver)

            existente = conexion.execute("""
                SELECT 1 FROM reparto_serie
                WHERE id_serie = ?
                  AND id_actor = ?
                  AND id_personaje = ?
            """, (id_serie, id_actor, id_personaje)).fetchone()

            if existente:
                flash("Ese actor ya interpreta a ese personaje aquí.", "error")
                return redirect(volver)

            conexion.execute("""
                INSERT INTO reparto_serie (
                    id_serie, id_actor, id_personaje
                )
                VALUES (?, ?, ?)
            """, (id_serie, id_actor, id_personaje))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo agregar al reparto.", "error")
        return redirect(volver)

    flash("Reparto actualizado correctamente.", "exito")
    return redirect(volver)


@app.route(
    "/series/<int:id_serie>/reparto/<int:id_reparto>/quitar",
    methods=["POST"]
)
@admin_requerido
def quitar_reparto_serie(id_serie, id_reparto):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM reparto_serie
            WHERE id_reparto = ?
              AND id_serie = ?
        """, (id_reparto, id_serie))

        if resultado.rowcount == 0:
            flash("No se encontró esa fila del reparto.", "error")
        else:
            conexion.commit()
            flash("Quitado del reparto.", "exito")

    return redirect(url_for("detalle_serie", id_serie=id_serie))

@app.route("/series/proponer-nueva", methods=["GET", "POST"])
@login_requerido
def proponer_serie_nueva():
    if session.get("rol") == "admin":
        flash(
            "Los administradores registran las series directamente.",
            "error"
        )
        return redirect(url_for("agregar_serie"))

    if request.method == "GET":
        with closing(conectar_bd()) as conexion:
            universos = conexion.execute("""
                SELECT * FROM universos ORDER BY nombre
            """).fetchall()

            fases = conexion.execute("""
                SELECT f.id_fase, f.nombre, f.numero,
                       f.id_universo, u.nombre AS universo
                FROM fases f
                JOIN universos u
                    ON f.id_universo = u.id_universo
                ORDER BY u.nombre, f.numero
            """).fetchall()

        return render_template(
            "proponer_serie.html",
            universos=universos,
            fases=fases
        )

    # ----- POST: guardar la propuesta -----
    volver = url_for("proponer_serie_nueva")

    titulo = request.form.get("titulo", "").strip()
    anio_texto = request.form.get("anio", "").strip()
    temporadas_texto = request.form.get("temporadas", "").strip()
    sinopsis = request.form.get("sinopsis", "").strip()
    portada = request.form.get("portada", "").strip()
    trailer = request.form.get("trailer", "").strip()
    fase_texto = request.form.get("id_fase", "").strip()
    universo_texto = request.form.get("id_universo", "").strip()

    if not titulo:
        flash("El título de la serie es obligatorio.", "error")
        return redirect(volver)

    if not universo_texto:
        flash("Selecciona el universo de la serie.", "error")
        return redirect(volver)

    try:
        anio = int(anio_texto) if anio_texto else None
        temporadas = int(temporadas_texto) if temporadas_texto else None
        id_fase = int(fase_texto) if fase_texto else None
        id_universo = int(universo_texto)

        if anio is not None and not 1888 <= anio <= 2100:
            raise ValueError

        if temporadas is not None and temporadas < 1:
            raise ValueError

        if id_fase is not None and id_fase < 1:
            raise ValueError

        if id_universo < 1:
            raise ValueError

    except ValueError:
        flash("Revisa el año, las temporadas, la fase y el universo.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            universo = conexion.execute("""
                SELECT id_universo FROM universos
                WHERE id_universo = ?
            """, (id_universo,)).fetchone()

            if universo is None:
                flash("El universo seleccionado no existe.", "error")
                return redirect(volver)

            if id_fase is not None:
                fase = conexion.execute("""
                    SELECT id_universo FROM fases
                    WHERE id_fase = ?
                """, (id_fase,)).fetchone()

                if fase is None:
                    flash("La fase seleccionada no existe.", "error")
                    return redirect(volver)

                if fase["id_universo"] != id_universo:
                    flash(
                        "La fase seleccionada no pertenece "
                        "al universo elegido.",
                        "error"
                    )
                    return redirect(volver)

            existente = conexion.execute("""
                SELECT 1 FROM series
                WHERE lower(titulo) = lower(?)
                  AND anio_inicio IS ?
            """, (titulo, anio)).fetchone()

            if existente:
                flash("Ya existe una serie con ese título y año.", "error")
                return redirect(volver)

            pendiente = conexion.execute("""
                SELECT 1 FROM propuestas_serie
                WHERE id_usuario = ?
                  AND lower(titulo) = lower(?)
                  AND estado = 'pendiente'
            """, (session["id_usuario"], titulo)).fetchone()

            if pendiente:
                flash(
                    "Ya tienes una propuesta pendiente con ese título.",
                    "error"
                )
                return redirect(url_for("catalogo_series"))

            conexion.execute("""
                INSERT INTO propuestas_serie (
                    id_usuario, titulo, anio_inicio,
                    temporadas, sinopsis, portada,
                    trailer_url, id_fase, id_universo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session["id_usuario"], titulo, anio,
                temporadas, sinopsis, portada,
                trailer, id_fase, id_universo
            ))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo enviar la propuesta.", "error")
        return redirect(volver)

    flash(
        "Tu propuesta fue enviada. Un administrador la revisará.",
        "exito"
    )
    return redirect(url_for("catalogo_series"))

@app.route("/series/<int:id_serie>/valorar", methods=["POST"])
@login_requerido
def valorar_serie(id_serie):
    volver = url_for("detalle_serie", id_serie=id_serie)

    puntuacion_texto = request.form.get("puntuacion", "").strip()
    comentario = request.form.get("comentario", "").strip()

    try:
        puntuacion = int(puntuacion_texto)
    except ValueError:
        puntuacion = 0

    if not 1 <= puntuacion <= 5:
        flash("Elige una calificación de 1 a 5.", "error")
        return redirect(volver)

    if len(comentario) > 500:
        flash("El comentario puede tener hasta 500 caracteres.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            serie = conexion.execute("""
                SELECT 1 FROM series WHERE id_serie = ?
            """, (id_serie,)).fetchone()

            if serie is None:
                flash("No se encontró esa serie.", "error")
                return redirect(url_for("catalogo_series"))

            conexion.execute("""
                INSERT INTO valoraciones_serie (
                    id_usuario, id_serie, puntuacion, comentario
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT (id_usuario, id_serie) DO UPDATE SET
                    puntuacion = excluded.puntuacion,
                    comentario = excluded.comentario,
                    fecha_edicion = datetime('now')
            """, (session["id_usuario"], id_serie, puntuacion, comentario))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo guardar tu calificación.", "error")
        return redirect(volver)

    flash("Tu calificación fue guardada.", "exito")
    return redirect(volver)


@app.route(
    "/series/<int:id_serie>/valoraciones/<int:id_valoracion>/eliminar",
    methods=["POST"]
)
@login_requerido
def eliminar_valoracion_serie(id_serie, id_valoracion):
    es_admin = 1 if session.get("rol") == "admin" else 0

    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM valoraciones_serie
            WHERE id_valoracion = ?
              AND id_serie = ?
              AND (id_usuario = ? OR ? = 1)
        """, (id_valoracion, id_serie, session["id_usuario"], es_admin))

        if resultado.rowcount == 0:
            flash(
                "No se pudo borrar: no existe o no es tuya.",
                "error"
            )
        else:
            conexion.commit()
            flash("Calificación eliminada.", "exito")

    return redirect(url_for("detalle_serie", id_serie=id_serie))

@app.route("/series/agregar")
@admin_requerido
def agregar_serie():
    with closing(conectar_bd()) as conexion:
        universos = conexion.execute("""
            SELECT * FROM universos ORDER BY nombre
        """).fetchall()

        fases = conexion.execute("""
            SELECT f.id_fase, f.nombre, f.numero,
                   f.id_universo, u.nombre AS universo
            FROM fases f
            JOIN universos u
                ON f.id_universo = u.id_universo
            ORDER BY u.nombre, f.numero
        """).fetchall()

    return render_template(
        "agregar_serie.html",
        universos=universos,
        fases=fases
    )

@app.route(
    "/series/<int:id_serie>/proponer-cambio",
    methods=["GET", "POST"]
)
@login_requerido
def proponer_cambio_serie(id_serie):
    if session.get("rol") == "admin":
        flash(
            "Los administradores editan las series directamente.",
            "error"
        )
        return redirect(url_for("catalogo_series"))

    with closing(conectar_bd()) as conexion:
        serie = conexion.execute("""
            SELECT * FROM series WHERE id_serie = ?
        """, (id_serie,)).fetchone()

        universos = conexion.execute("""
            SELECT * FROM universos ORDER BY nombre
        """).fetchall()

        fases = conexion.execute("""
            SELECT f.id_fase, f.nombre, f.numero,
                   f.id_universo, u.nombre AS universo
            FROM fases f
            JOIN universos u
                ON f.id_universo = u.id_universo
            ORDER BY u.nombre, f.numero
        """).fetchall()

    if serie is None:
        flash("No se encontró esa serie.", "error")
        return redirect(url_for("catalogo_series"))

    if request.method == "GET":
        return render_template(
            "proponer_cambio_serie.html",
            serie=serie,
            universos=universos,
            fases=fases
        )

    # ----- POST: guardar la solicitud -----
    volver = url_for("proponer_cambio_serie", id_serie=id_serie)

    titulo = request.form.get("titulo", "").strip()
    anio_texto = request.form.get("anio", "").strip()
    temporadas_texto = request.form.get("temporadas", "").strip()
    sinopsis = request.form.get("sinopsis", "").strip()
    portada = request.form.get("portada", "").strip()
    trailer = request.form.get("trailer", "").strip()
    fase_texto = request.form.get("id_fase", "").strip()
    universo_texto = request.form.get("id_universo", "").strip()

    if not titulo:
        flash("El título es obligatorio.", "error")
        return redirect(volver)

    if not universo_texto:
        flash("Selecciona el universo de la serie.", "error")
        return redirect(volver)

    try:
        anio = int(anio_texto) if anio_texto else None
        temporadas = int(temporadas_texto) if temporadas_texto else None
        id_fase = int(fase_texto) if fase_texto else None
        id_universo = int(universo_texto)

        if anio is not None and not 1888 <= anio <= 2100:
            raise ValueError

        if temporadas is not None and temporadas < 1:
            raise ValueError

        if id_fase is not None and id_fase < 1:
            raise ValueError

        if id_universo < 1:
            raise ValueError

    except ValueError:
        flash("Revisa el año, las temporadas, la fase y el universo.", "error")
        return redirect(volver)

    propuesta = (
        titulo, anio, temporadas, sinopsis,
        portada, trailer, id_fase, id_universo
    )
    actual = (
        serie["titulo"], serie["anio_inicio"],
        serie["temporadas"], serie["sinopsis"] or "",
        serie["portada"] or "", serie["trailer_url"] or "",
        serie["id_fase"], serie["id_universo"]
    )

    if propuesta == actual:
        flash("No cambiaste nada de la serie.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            universo = conexion.execute("""
                SELECT id_universo FROM universos
                WHERE id_universo = ?
            """, (id_universo,)).fetchone()

            if universo is None:
                flash("El universo seleccionado no existe.", "error")
                return redirect(volver)

            if id_fase is not None:
                fase = conexion.execute("""
                    SELECT id_universo FROM fases
                    WHERE id_fase = ?
                """, (id_fase,)).fetchone()

                if fase is None:
                    flash("La fase seleccionada no existe.", "error")
                    return redirect(volver)

                if fase["id_universo"] != id_universo:
                    flash(
                        "La fase seleccionada no pertenece "
                        "al universo elegido.",
                        "error"
                    )
                    return redirect(volver)

            pendiente = conexion.execute("""
                SELECT 1 FROM solicitudes_serie
                WHERE id_usuario = ?
                  AND id_serie = ?
                  AND estado = 'pendiente'
            """, (session["id_usuario"], id_serie)).fetchone()

            if pendiente:
                flash(
                    "Ya tienes una solicitud pendiente para esta serie.",
                    "error"
                )
                return redirect(url_for("catalogo_series"))

            conexion.execute("""
                INSERT INTO solicitudes_serie (
                    id_usuario, id_serie, titulo, anio_inicio,
                    temporadas, sinopsis, portada, trailer_url,
                    id_fase, id_universo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session["id_usuario"], id_serie, titulo, anio,
                temporadas, sinopsis, portada, trailer,
                id_fase, id_universo
            ))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo enviar la solicitud.", "error")
        return redirect(volver)

    flash(
        "Tu solicitud fue enviada. Un administrador la revisará.",
        "exito"
    )
    return redirect(url_for("catalogo_series"))

@app.route("/series/<int:id_serie>/editar", methods=["GET", "POST"])
@admin_requerido
def editar_serie(id_serie):
    with closing(conectar_bd()) as conexion:
        serie = conexion.execute("""
            SELECT * FROM series WHERE id_serie = ?
        """, (id_serie,)).fetchone()

        universos = conexion.execute("""
            SELECT * FROM universos ORDER BY nombre
        """).fetchall()

        fases = conexion.execute("""
            SELECT f.id_fase, f.nombre, f.numero,
                   f.id_universo, u.nombre AS universo
            FROM fases f
            JOIN universos u
                ON f.id_universo = u.id_universo
            ORDER BY u.nombre, f.numero
        """).fetchall()

    if serie is None:
        flash("No se encontró esa serie.", "error")
        return redirect(url_for("catalogo_series"))

    if request.method == "GET":
        return render_template(
            "editar_serie.html",
            serie=serie,
            universos=universos,
            fases=fases
        )

    # ----- POST: guardar los cambios -----
    volver = url_for("editar_serie", id_serie=id_serie)

    titulo = request.form.get("titulo", "").strip()
    anio_texto = request.form.get("anio", "").strip()
    temporadas_texto = request.form.get("temporadas", "").strip()
    sinopsis = request.form.get("sinopsis", "").strip()
    portada = request.form.get("portada", "").strip()
    trailer = request.form.get("trailer", "").strip()
    fase_texto = request.form.get("id_fase", "").strip()
    universo_texto = request.form.get("id_universo", "").strip()

    if not titulo:
        flash("El título es obligatorio.", "error")
        return redirect(volver)

    if not universo_texto:
        flash("Selecciona el universo de la serie.", "error")
        return redirect(volver)

    try:
        anio = int(anio_texto) if anio_texto else None
        temporadas = int(temporadas_texto) if temporadas_texto else None
        id_fase = int(fase_texto) if fase_texto else None
        id_universo = int(universo_texto)

        if anio is not None and not 1888 <= anio <= 2100:
            raise ValueError

        if temporadas is not None and temporadas < 1:
            raise ValueError

        if id_fase is not None and id_fase < 1:
            raise ValueError

        if id_universo < 1:
            raise ValueError

    except ValueError:
        flash("Revisa el año, las temporadas, la fase y el universo.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            universo = conexion.execute("""
                SELECT id_universo FROM universos
                WHERE id_universo = ?
            """, (id_universo,)).fetchone()

            if universo is None:
                flash("El universo seleccionado no existe.", "error")
                return redirect(volver)

            if id_fase is not None:
                fase = conexion.execute("""
                    SELECT id_universo FROM fases
                    WHERE id_fase = ?
                """, (id_fase,)).fetchone()

                if fase is None:
                    flash("La fase seleccionada no existe.", "error")
                    return redirect(volver)

                if fase["id_universo"] != id_universo:
                    flash(
                        "La fase seleccionada no pertenece "
                        "al universo elegido.",
                        "error"
                    )
                    return redirect(volver)

            resultado = conexion.execute("""
                UPDATE series
                SET titulo = ?, anio_inicio = ?, temporadas = ?,
                    sinopsis = ?, portada = ?, trailer_url = ?,
                    id_fase = ?, id_universo = ?
                WHERE id_serie = ?
            """, (
                titulo, anio, temporadas, sinopsis,
                portada, trailer, id_fase, id_universo,
                id_serie
            ))

            if resultado.rowcount == 0:
                flash("No se encontró esa serie.", "error")
                return redirect(url_for("catalogo_series"))

            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo actualizar: universo o fase inexistente.", "error")
        return redirect(volver)

    flash("Serie actualizada correctamente.", "exito")
    return redirect(url_for("catalogo_series"))


@app.route("/series/<int:id_serie>/eliminar", methods=["POST"])
@admin_requerido
def eliminar_serie(id_serie):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM series
            WHERE id_serie = ?
        """, (id_serie,))

        if resultado.rowcount == 0:
            flash("No se encontró esa serie.", "error")
        else:
            conexion.commit()
            flash("Serie eliminada correctamente.", "exito")

    return redirect(url_for("catalogo_series"))


@app.route("/series/nueva", methods=["POST"])
@admin_requerido
def nueva_serie():
    titulo = request.form.get("titulo", "").strip()
    anio_texto = request.form.get("anio", "").strip()
    temporadas_texto = request.form.get("temporadas", "").strip()
    sinopsis = request.form.get("sinopsis", "").strip()
    portada = request.form.get("portada", "").strip()
    trailer = request.form.get("trailer", "").strip()
    fase_texto = request.form.get("id_fase", "").strip()
    universo_texto = request.form.get("id_universo", "").strip()

    if not titulo:
        flash("El título de la serie es obligatorio.", "error")
        return redirect(url_for("agregar_serie"))

    if not universo_texto:
        flash("Selecciona el universo de la serie.", "error")
        return redirect(url_for("agregar_serie"))

    try:
        anio = int(anio_texto) if anio_texto else None
        temporadas = int(temporadas_texto) if temporadas_texto else None
        id_fase = int(fase_texto) if fase_texto else None
        id_universo = int(universo_texto)

        if anio is not None and not 1888 <= anio <= 2100:
            raise ValueError

        if temporadas is not None and temporadas < 1:
            raise ValueError

        if id_fase is not None and id_fase < 1:
            raise ValueError

        if id_universo < 1:
            raise ValueError

        with closing(conectar_bd()) as conexion:
            # 1. Validar que el universo exista
            universo = conexion.execute("""
                SELECT id_universo
                FROM universos
                WHERE id_universo = ?
            """, (id_universo,)).fetchone()

            if universo is None:
                flash("El universo seleccionado no existe.", "error")
                return redirect(url_for("agregar_serie"))

            # 2. Si eligió fase, validar que exista y que sea de ese universo
            if id_fase is not None:
                fase = conexion.execute("""
                    SELECT id_universo
                    FROM fases
                    WHERE id_fase = ?
                """, (id_fase,)).fetchone()

                if fase is None:
                    flash("La fase seleccionada no existe.", "error")
                    return redirect(url_for("agregar_serie"))

                if fase["id_universo"] != id_universo:
                    flash(
                        "La fase seleccionada no pertenece "
                        "al universo elegido.",
                        "error"
                    )
                    return redirect(url_for("agregar_serie"))

            # 3. Guardar la serie
            conexion.execute("""
                INSERT INTO series (
                    titulo, anio_inicio, temporadas,
                    sinopsis, portada, trailer_url,
                    id_fase, id_universo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                titulo, anio, temporadas, sinopsis,
                portada, trailer, id_fase, id_universo
            ))
            conexion.commit()

        flash("Serie registrada correctamente.", "exito")

    except ValueError:
        flash("Revisa el año, las temporadas, la fase y el universo.", "error")

    except sqlite3.IntegrityError:
        flash("No se pudo registrar: universo o fase inexistente.", "error")

    return redirect(url_for("agregar_serie"))

@app.route(
    "/peliculas/<int:id_pelicula>/proponer-cambio",
    methods=["GET", "POST"]
)
@login_requerido
def proponer_cambio(id_pelicula):
    if session.get("rol") == "admin":
        flash(
            "Los administradores editan las películas directamente.",
            "error"
        )
        return redirect(url_for("catalogo_peliculas"))

    with closing(conectar_bd()) as conexion:
        pelicula = conexion.execute("""
            SELECT * FROM peliculas WHERE id_pelicula = ?
        """, (id_pelicula,)).fetchone()

        universos = conexion.execute("""
            SELECT * FROM universos ORDER BY nombre
        """).fetchall()

        fases = conexion.execute("""
            SELECT f.id_fase, f.nombre, f.numero,
                   f.id_universo, u.nombre AS universo
            FROM fases f
            JOIN universos u
                ON f.id_universo = u.id_universo
            ORDER BY u.nombre, f.numero
        """).fetchall()

    if pelicula is None:
        flash("No se encontró esa película.", "error")
        return redirect(url_for("catalogo_peliculas"))

    if request.method == "GET":
        return render_template(
            "proponer_cambio.html",
            pelicula=pelicula,
            universos=universos,
            fases=fases
        )

    # ----- POST: guardar la solicitud -----
    volver = url_for("proponer_cambio", id_pelicula=id_pelicula)

    titulo = request.form.get("titulo", "").strip()
    anio_texto = request.form.get("anio", "").strip()
    duracion_texto = request.form.get("duracion", "").strip()
    sinopsis = request.form.get("sinopsis", "").strip()
    portada = request.form.get("portada", "").strip()
    trailer = request.form.get("trailer", "").strip()
    fase_texto = request.form.get("id_fase", "").strip()
    universo_texto = request.form.get("id_universo", "").strip()

    if not titulo:
        flash("El título es obligatorio.", "error")
        return redirect(volver)

    if not universo_texto:
        flash("Selecciona el universo de la película.", "error")
        return redirect(volver)

    try:
        anio = int(anio_texto) if anio_texto else None
        duracion = int(duracion_texto) if duracion_texto else None
        id_fase = int(fase_texto) if fase_texto else None
        id_universo = int(universo_texto)

        if anio is not None and not 1888 <= anio <= 2100:
            raise ValueError

        if duracion is not None and duracion < 1:
            raise ValueError

        if id_fase is not None and id_fase < 1:
            raise ValueError

        if id_universo < 1:
            raise ValueError

    except ValueError:
        flash("Revisa el año, la duración, la fase y el universo.", "error")
        return redirect(volver)

    propuesta = (
        titulo, anio, duracion, sinopsis,
        portada, trailer, id_fase, id_universo
    )
    actual = (
        pelicula["titulo"], pelicula["anio_estreno"],
        pelicula["duracion_minutos"], pelicula["sinopsis"] or "",
        pelicula["portada"] or "", pelicula["trailer_url"] or "",
        pelicula["id_fase"], pelicula["id_universo"]
    )

    if propuesta == actual:
        flash("No cambiaste nada de la película.", "error")
        return redirect(volver)

    try:
        with closing(conectar_bd()) as conexion:
            universo = conexion.execute("""
                SELECT id_universo FROM universos
                WHERE id_universo = ?
            """, (id_universo,)).fetchone()

            if universo is None:
                flash("El universo seleccionado no existe.", "error")
                return redirect(volver)

            if id_fase is not None:
                fase = conexion.execute("""
                    SELECT id_universo FROM fases
                    WHERE id_fase = ?
                """, (id_fase,)).fetchone()

                if fase is None:
                    flash("La fase seleccionada no existe.", "error")
                    return redirect(volver)

                if fase["id_universo"] != id_universo:
                    flash(
                        "La fase seleccionada no pertenece "
                        "al universo elegido.",
                        "error"
                    )
                    return redirect(volver)

            pendiente = conexion.execute("""
                SELECT 1 FROM solicitudes_cambio
                WHERE id_usuario = ?
                  AND id_pelicula = ?
                  AND estado = 'pendiente'
            """, (session["id_usuario"], id_pelicula)).fetchone()

            if pendiente:
                flash(
                    "Ya tienes una solicitud pendiente para esta película.",
                    "error"
                )
                return redirect(url_for("catalogo_peliculas"))

            conexion.execute("""
                INSERT INTO solicitudes_cambio (
                    id_usuario, id_pelicula, titulo, anio_estreno,
                    duracion_minutos, sinopsis, portada, trailer_url,
                    id_fase, id_universo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session["id_usuario"], id_pelicula, titulo, anio,
                duracion, sinopsis, portada, trailer,
                id_fase, id_universo
            ))
            conexion.commit()

    except sqlite3.IntegrityError:
        flash("No se pudo enviar la solicitud.", "error")
        return redirect(volver)

    flash(
        "Tu solicitud fue enviada. Un administrador la revisará.",
        "exito"
    )
    return redirect(url_for("catalogo_peliculas"))

@app.route("/peliculas/editar/<int:id_pelicula>", methods=["POST"])
@admin_requerido
def editar_pelicula(id_pelicula):
    titulo = request.form.get("titulo", "").strip()
    anio_texto = request.form.get("anio", "").strip()
    duracion_texto = request.form.get("duracion", "").strip()
    sinopsis = request.form.get("sinopsis", "").strip()
    portada = request.form.get("portada", "").strip()
    trailer = request.form.get("trailer", "").strip()
    fase_texto = request.form.get("id_fase", "").strip()
    universo_texto = request.form.get("id_universo", "").strip()

    if not titulo:
        flash("El título es obligatorio.", "error")
        return redirect(url_for("catalogo_peliculas"))

    if not universo_texto:
        flash("Selecciona el universo de la película.", "error")
        return redirect(url_for("catalogo_peliculas"))

    try:
        anio = int(anio_texto) if anio_texto else None
        duracion = int(duracion_texto) if duracion_texto else None
        id_fase = int(fase_texto) if fase_texto else None
        id_universo = int(universo_texto)

        if anio is not None and not 1888 <= anio <= 2100:
            raise ValueError

        if duracion is not None and duracion < 1:
            raise ValueError

        if id_fase is not None and id_fase < 1:
            raise ValueError

        if id_universo < 1:
            raise ValueError

        with closing(conectar_bd()) as conexion:
            # 1. Validar que el universo exista
            universo = conexion.execute("""
                SELECT id_universo
                FROM universos
                WHERE id_universo = ?
            """, (id_universo,)).fetchone()

            if universo is None:
                flash("El universo seleccionado no existe.", "error")
                return redirect(url_for("catalogo_peliculas"))

            # 2. Si eligió fase, validar que exista y que sea de ese universo
            if id_fase is not None:
                fase = conexion.execute("""
                    SELECT id_universo
                    FROM fases
                    WHERE id_fase = ?
                """, (id_fase,)).fetchone()

                if fase is None:
                    flash("La fase seleccionada no existe.", "error")
                    return redirect(url_for("catalogo_peliculas"))

                if fase["id_universo"] != id_universo:
                    flash(
                        "La fase seleccionada no pertenece "
                        "al universo elegido.",
                        "error"
                    )
                    return redirect(url_for("catalogo_peliculas"))

            # 3. Actualizar la película, incluyendo su universo
            resultado = conexion.execute("""
                UPDATE peliculas
                SET titulo = ?, anio_estreno = ?,
                    duracion_minutos = ?, sinopsis = ?,
                    portada = ?, trailer_url = ?,
                    id_fase = ?, id_universo = ?
                WHERE id_pelicula = ?
            """, (
                titulo, anio, duracion, sinopsis,
                portada, trailer, id_fase, id_universo,
                id_pelicula
            ))

            if resultado.rowcount == 0:
                flash("No se encontró esa película.", "error")
            else:
                conexion.commit()
                flash("Película actualizada correctamente.", "exito")

    except ValueError:
        flash("Revisa el año, la duración, la fase y el universo.", "error")

    except sqlite3.IntegrityError:
        flash("No se pudo actualizar: universo o fase inexistente.", "error")

    return redirect(url_for("catalogo_peliculas"))


@app.route("/peliculas/eliminar/<int:id_pelicula>", methods=["POST"])
@admin_requerido
def eliminar_pelicula(id_pelicula):
    with closing(conectar_bd()) as conexion:
        resultado = conexion.execute("""
            DELETE FROM peliculas
            WHERE id_pelicula = ?
        """, (id_pelicula,))

        if resultado.rowcount == 0:
            flash("No se encontró esa película.", "error")
        else:
            conexion.commit()
            flash("Película eliminada correctamente.", "exito")

    return redirect(url_for("catalogo_peliculas"))


if __name__ == "__main__":
    app.run(debug=True)