import { NextResponse } from 'next/server';

export async function GET() {
  const mockMatches = [
    { id: '4965737', homeName: '悉尼FC (Sydney FC)', awayName: '纽卡斯尔喷气机', time: '14:00', handicap: '-0.5', ev: 4.2, hasReport: true },
    { id: '4965735', homeName: '布里斯班狮吼', awayName: '惠灵顿凤凰', time: '16:30', handicap: '+0.25', ev: -1.5, hasReport: true },
    { id: '10003', homeName: '皇家马德里', awayName: '巴塞罗那', time: '23:00', handicap: '-0.25', ev: 2.1, hasReport: false }
  ];
  return NextResponse.json(mockMatches);
}
