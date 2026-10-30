
from app.schemas.transport import RouteLeg


class RouteService:
    @staticmethod
    def build_route(route_options: list[RouteLeg]) -> list[RouteLeg]:
        return list(route_options)
