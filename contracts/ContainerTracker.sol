// SPDX-License-Identifier: MIT
// ContainerTracker — VOC Port Smart Container Tracker (production path)
// Mirrors backend/core.py exactly: same status flow, same role gating,
// same auto payment-release on clearance. Deploy to Sepolia testnet with
// Hardhat (see contracts/HARDHAT.md) so every event is publicly verifiable.
pragma solidity ^0.8.24;

contract ContainerTracker {
    enum Status { NONE, ARRIVED, INSPECTED, CLEARED, PAYMENT_RELEASED, DISPATCHED }

    struct Shipment {
        Status status;
        string cargoCategory;
        string cargoType;
        string terminal;
        uint64 arrivedAt;
        address updatedBy;
    }

    mapping(bytes32 => Shipment) public shipments;
    mapping(address => string) public roles;          // wallet -> role name

    event Arrived(bytes32 indexed cid, string vessel, uint64 ts);
    event Inspected(bytes32 indexed cid, address indexed customs, uint64 ts);
    event Cleared(bytes32 indexed cid, address indexed portAuthority, uint64 ts);
    event PaymentReleased(bytes32 indexed cid, uint64 ts);   // automatic
    event Dispatched(bytes32 indexed cid, address indexed transporter, uint64 ts);

    error AccessDenied(string requiredRole);
    error InvalidTransition(Status current, Status attempted);

    constructor(address _system, address _customs, address _portAuthority,
                address _transporter) {
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

    function markArrived(bytes32 cid, string calldata cargoCategory,
                         string calldata cargoType, string calldata terminal,
                         string calldata vessel)
        external onlyRole("SYSTEM") {
        shipments[cid] = Shipment(Status.ARRIVED, cargoCategory, cargoType,
                                  terminal, uint64(block.timestamp), msg.sender);
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
        // --- AUTOMATION: clearance immediately releases payment ---
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

    function getStatus(bytes32 cid) external view returns (Status, uint64) {
        return (shipments[cid].status, shipments[cid].arrivedAt);
    }
}
