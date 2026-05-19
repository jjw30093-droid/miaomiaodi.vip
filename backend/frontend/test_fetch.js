const fetch = require('node-fetch');

async function testFetch() {
  try {
    console.log("Testing /api/v1/reports/latest...");
    const res = await fetch('http://localhost:8000/api/v1/reports/latest');
    console.log("Status:", res.status);
    const data = await res.json();
    console.log("Data length:", data.length);
    
    const matchId = data[0].id;
    console.log(`Testing /api/v1/report/${matchId}...`);
    const res2 = await fetch(`http://localhost:8000/api/v1/report/${matchId}`);
    console.log("Status:", res2.status);
    const data2 = await res2.json();
    console.log("Data keys:", Object.keys(data2));
  } catch (err) {
    console.error("Fetch Error:", err);
  }
}

testFetch();
