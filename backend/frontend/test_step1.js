const { getMatchReport } = require('./lib/fetchReport');

async function testFetch() {
  process.env.DB_PATH = '/Users/wanglujun/Desktop/Football_Data_Lake/25-26英超全数据.db';
  const matchId = '5130428';
  console.log(`Testing getMatchReport for ${matchId}...`);
  const report = await getMatchReport(matchId);
  
  if (report) {
    console.log('Success!');
    console.log('Home Prob:', report.homeProb);
    console.log('Away Prob:', report.awayProb);
    console.log('Inference:', report.inference);
    console.log('Radar Data (Home):', JSON.stringify(report.radarData?.home, null, 2));
    console.log('Radar Data (Away):', JSON.stringify(report.radarData?.away, null, 2));
  } else {
    console.log('Failed to fetch report.');
  }
}

testFetch();
