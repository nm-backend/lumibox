"""
Database router для будущих read replicas.

Сейчас не используется, но архитектура готова:
- Write → default
- Read → default (будет read replica)

Когда появится read replica, достаточно:
1. Добавить DATABASES["read"] в settings
2. Вернуть True в db_for_read для "read"
"""



class PrimaryReadRouter:
    """
    Routes database reads to a read replica (future).
    Currently all operations go to 'default'.
    """

    def db_for_read(self, model, **hints):
        """Reads go to default (will be read replica when configured)."""
        return "default"

    def db_for_write(self, model, **hints):
        """Writes always go to primary."""
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        """Allow relations between all objects."""
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Migrations only on primary."""
        return db == "default"
