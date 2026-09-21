# Optional: deploy the real contract to Sepolia testnet

The demo runs fully offline using the local hash-chained ledger in
`backend/core.py`. For the full "public, tamper-proof" claim, deploy this
contract so every event is verifiable on Etherscan.

```bash
npm install --save-dev hardhat @nomicfoundation/hardhat-toolbox
npx hardhat init          # choose empty project, add this file to contracts/
# put a Sepolia RPC URL + private key (a TEST wallet only!) into .env
npx hardhat run scripts/deploy.js --network sepolia
```

deploy.js sketch:
```js
const hre = require("hardhat");
module.exports = async () => {
  const T = await hre.ethers.getContractFactory("ContainerTracker");
  const c = await T.deploy(system, customs, portAuthority, transporter); // test wallets
  await c.waitForDeployment();
  console.log("ContainerTracker:", await c.getAddress());
};
```

Viva talking point: the local ledger and the contract encode *identical*
rules — the demo just swaps the storage layer.
