// SPDX-License-Identifier: MIT
pragma solidity ^0.8.18;

interface IERC20 {
    function approve(address spender, uint256 amount) external returns (bool);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract ArbExecutor {
    address public owner;
    address public immutable COLLATERAL; // USDC
    address public immutable CTF_EXCHANGE; // Polymarket Exchange

    constructor(address _collateral, address _ctfExchange) {
        owner = msg.sender;
        COLLATERAL = _collateral;
        CTF_EXCHANGE = _ctfExchange;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    /**
     * @dev Execute multiple trades atomically.
     * If ANY trade fails, the ENTIRE transaction reverts.
     * @param targets Array of target addresses (CTF Exchange)
     * @param data Array of calldata for each call (fillOrder)
     */
    function executeBatch(
        address[] calldata targets,
        bytes[] calldata data
    ) external onlyOwner {
        require(targets.length == data.length, "Length mismatch");

        for (uint256 i = 0; i < targets.length; i++) {
            (bool success, ) = targets[i].call(data[i]);
            require(success, "Trade failed: Reverting batch");
        }
    }

    /**
     * @dev Approve the exchange to spend our tokens
     */
    function approveExchange(uint256 amount) external onlyOwner {
        IERC20(COLLATERAL).approve(CTF_EXCHANGE, amount);
    }

    /**
     * @dev Withdraw funds back to owner
     */
    function withdraw(address token) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        require(balance > 0, "No balance");
        IERC20(token).transfer(owner, balance);
    }

    // Allow receiving ETH/MATIC
    receive() external payable {}
}
