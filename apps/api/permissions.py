from rest_framework import permissions


class IsAuthorOrReadOnly(permissions.BasePermission):
    """
    Читать может любой, изменять — только автор записи.

    Проверка на уровне объекта: без неё авторизованный пользователь
    отредактировал бы чужой отзыв, подставив его номер в адрес.
    """

    message = "Изменять можно только свои записи."

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        return obj.user_id == request.user.id
