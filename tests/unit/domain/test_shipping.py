from app.domain.shipping.models import Shipment, ShipmentStatus


def test_shipment_is_created_for_order() -> None:
    shipment = Shipment.create_for_order("order-1", shipment_id="shipment-1")

    assert shipment.order_id == "order-1"
    assert shipment.status == ShipmentStatus.CREATED

