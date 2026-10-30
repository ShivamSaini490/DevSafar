
from app.schemas.transport import RouteLeg, TransportOption


class TransportService:
    @staticmethod
    def from_route_legs(route_legs: list[RouteLeg]) -> list[TransportOption]:
        """Project verified road legs into the transport comparison contract."""

        return [
            TransportOption(
                origin=leg.origin,
                destination=leg.destination,
                mode=leg.mode,
                provider="osrm+fuel_formula",
                duration_minutes=leg.duration_minutes,
                distance_km=leg.distance_km,
                price=leg.price.model_copy(deep=True),
                availability="unknown",
            )
            for leg in route_legs
        ]
