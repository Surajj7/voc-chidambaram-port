// SPDX-License-Identifier: MIT
// ContainerTracker — VOC Port Smart Container Tracker (production path)
// Smart Cities Mission & Sagarmala Digital Port Initiative - Thoothukudi
// Mirrors backend/core.py: identical role gating, identical state transitions,
// and automated escrow payment release on customs clearance.
pragma solidity ^0.8.24;

contract ContainerTracker {
    enum Status {
        NONE,
        INBOUND,          // Yet to Arrive: Manifest filed by shipping line
        ARRIVED,          // In Port: Vessel berthed, offloaded at Berth IX/VIII
        INSPECTED,        // In Port: Customs physical examination completed
        CLEARED,          // In Port: Port Authority clearance approved
        PAYMENT_RELEASED, // In Port: Smart contract auto-released port charges
        DISPATCHED,       // Left Port: Transporter mounted container at Gate 1
        DEPARTED          // Left Port: Outer RFID sensor confirmed highway transit
    }

    struct Shipment {
        Status status;
        string cargoCategory;
        string cargoType;
        string terminal;
        string vessel;
        uint64 arrivedAt;
        address updatedBy;
    }

    mapping(bytes32 => Shipment) public shipments;
    mapping(address => string) public roles;          // wallet -> role name

    event Inbound(bytes32 indexed cid, string vessel, address indexed shippingLine, uint64 ts);
    event Arrived(bytes32 indexed cid, string vessel, uint64 ts);
    event Inspected(bytes32 indexed cid, address indexed customs, uint64 ts);
    event Cleared(bytes32 indexed cid, address indexed portAuthority, uint64 ts);
    event PaymentReleased(bytes32 indexed cid, uint64 ts);   // automatic escrow
    event Dispatched(bytes32 indexed cid, address indexed transporter, uint64 ts);
    event Departed(bytes32 indexed cid, uint64 ts);

    error AccessDenied(string requiredRole);
    error InvalidTransition(Status current, Status attempted);

    constructor(
        address _shippingLine,
        address _system,
        address _customs,
        address _portAuthority,
        address _transporter
    ) {
        roles[_shippingLine]  = "SHIPPING_LINE";
        roles[_system]        = "SYSTEM";
        roles[_customs]       = "CUSTOMS";
        roles[_portAuthority] = "PORT_AUTHORITY";
        roles[_transporter]   = "TRANSPORTER";
    }

    modifier onlyRole(string memory required) {
        if (keccak256(bytes(roles[msg.sender])) != keccak256(bytes(required)))
            revert AccessDenied(required);
        _;
    }

    function markInbound(
        bytes32 cid,
        string calldata cargoCategory,
        string calldata cargoType,
        string calldata terminal,
        string calldata vessel
    ) external onlyRole("SHIPPING_LINE") {
        if (shipments[cid].status != Status.NONE)
            revert InvalidTransition(shipments[cid].status, Status.INBOUND);

        shipments[cid] = Shipment(
            Status.INBOUND, cargoCategory, cargoType, terminal, vessel,
            uint64(block.timestamp), msg.sender
        );
        emit Inbound(cid, vessel, msg.sender, uint64(block.timestamp));
    }

    function markArrived(bytes32 cid, string calldata vessel) external onlyRole("SYSTEM") {
        Status cur = shipments[cid].status;
        if (cur != Status.INBOUND && cur != Status.NONE)
            revert InvalidTransition(cur, Status.ARRIVED);

        shipments[cid].status = Status.ARRIVED;
        shipments[cid].updatedBy = msg.sender;
        emit Arrived(cid, vessel, uint64(block.timestamp));
    }

    function markInspected(bytes32 cid) external onlyRole("CUSTOMS") {
        if (shipments[cid].status != Status.ARRIVED)
            revert InvalidTransition(shipments[cid].status, Status.INSPECTED);
        shipments[cid].status = Status.INSPECTED;
        shipments[cid].updatedBy = msg.sender;
        emit Inspected(cid, msg.sender, uint64(block.timestamp));
    }

    function markCleared(bytes32 cid) external onlyRole("PORT_AUTHORITY") {
        if (shipments[cid].status != Status.INSPECTED)
            revert InvalidTransition(shipments[cid].status, Status.CLEARED);

        // --- AUTOMATION: clearance immediately triggers escrow payment release ---
        shipments[cid].status = Status.PAYMENT_RELEASED;
        shipments[cid].updatedBy = msg.sender;
        emit Cleared(cid, msg.sender, uint64(block.timestamp));
        emit PaymentReleased(cid, uint64(block.timestamp));
    }

    function markDispatched(bytes32 cid) external onlyRole("TRANSPORTER") {
        if (shipments[cid].status != Status.PAYMENT_RELEASED)
            revert InvalidTransition(shipments[cid].status, Status.DISPATCHED);
        shipments[cid].status = Status.DISPATCHED;
        shipments[cid].updatedBy = msg.sender;
        emit Dispatched(cid, msg.sender, uint64(block.timestamp));
    }

    function markDeparted(bytes32 cid) external onlyRole("SYSTEM") {
        if (shipments[cid].status != Status.DISPATCHED)
            revert InvalidTransition(shipments[cid].status, Status.DEPARTED);
        shipments[cid].status = Status.DEPARTED;
        shipments[cid].updatedBy = msg.sender;
        emit Departed(cid, uint64(block.timestamp));
    }

    function getStatus(bytes32 cid) external view returns (Status, uint64) {
        return (shipments[cid].status, shipments[cid].arrivedAt);
    }
}
