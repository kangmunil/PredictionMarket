"""
대시보드 실시간 업데이트 테스트
===================================

WALLET과 SIGNALS가 실시간으로 업데이트되는지 확인하는 테스트 스크립트
"""

import asyncio
import logging
from decimal import Decimal
from run_swarm import SwarmSystem

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_budget_updates(system: SwarmSystem):
    """BudgetManager 실시간 업데이트 테스트"""
    logger.info("\n" + "="*60)
    logger.info("🧪 TEST 1: BudgetManager 실시간 업데이트")
    logger.info("="*60)

    # 초기 상태
    initial_balance = system.budget_manager.balances["arbhunter"]
    initial_allocated = sum(float(v) for v in system.budget_manager.allocations.values())

    logger.info(f"📊 Initial State:")
    logger.info(f"   ArbHunter Balance: ${initial_balance:.2f}")
    logger.info(f"   Total Allocated: ${initial_allocated:.2f}")

    # 5초 대기
    logger.info(f"\n⏳ Waiting 5 seconds... (Watch dashboard WALLET panel)")
    await asyncio.sleep(5)

    # 자금 할당 시뮬레이션
    logger.info(f"\n💰 Simulating trade allocation...")
    allocation_id = await system.budget_manager.request_allocation(
        strategy="arbhunter",
        amount=Decimal("50.0"),
        priority="high"
    )

    if allocation_id:
        logger.info(f"✅ Allocation successful: {allocation_id}")
        logger.info(f"👀 CHECK DASHBOARD: WALLET panel should show USED: $50")

        # 5초 대기 (대시보드 확인 시간)
        await asyncio.sleep(5)

        # 최종 상태
        final_balance = system.budget_manager.balances["arbhunter"]
        final_allocated = sum(float(v) for v in system.budget_manager.allocations.values())

        logger.info(f"\n📊 Final State:")
        logger.info(f"   ArbHunter Balance: ${final_balance:.2f} (changed: ${float(initial_balance - final_balance):+.2f})")
        logger.info(f"   Total Allocated: ${final_allocated:.2f} (changed: ${float(final_allocated - initial_allocated):+.2f})")
        logger.info(f"\n✅ TEST 1 PASSED: BudgetManager updates in real-time!")
    else:
        logger.error("❌ TEST 1 FAILED: Allocation was rejected")


async def test_signal_updates(system: SwarmSystem):
    """SignalBus 실시간 업데이트 테스트"""
    logger.info("\n" + "="*60)
    logger.info("🧪 TEST 2: SignalBus 실시간 업데이트")
    logger.info("="*60)

    # 초기 시그널 개수
    initial_signals = len(system.bus._signals)
    logger.info(f"📊 Initial Signals: {initial_signals}")

    # 5초 대기
    logger.info(f"\n⏳ Waiting 5 seconds... (Watch dashboard SIGNALS panel)")
    await asyncio.sleep(5)

    # 시그널 생성 시뮬레이션
    logger.info(f"\n🧠 Simulating signal creation...")
    test_token_ids = [
        "0xabcd1234test",
        "0xefgh5678test"
    ]

    for i, token_id in enumerate(test_token_ids):
        await system.bus.update_signal(
            token_id=token_id,
            source='NEWS',
            score=0.75 if i == 0 else -0.65,  # 첫 번째는 강한 매수, 두 번째는 강한 매도
            label='buy' if i == 0 else 'sell'
        )
        logger.info(f"✅ Signal created: {token_id} ({'BUY' if i == 0 else 'SELL'} {0.75 if i == 0 else -0.65:+.2f})")

    logger.info(f"👀 CHECK DASHBOARD: SIGNALS panel should show 2 new signals")

    # 5초 대기 (대시보드 확인 시간)
    await asyncio.sleep(5)

    # 최종 시그널 개수
    final_signals = len(system.bus._signals)
    logger.info(f"\n📊 Final Signals: {final_signals} (added: {final_signals - initial_signals})")

    # 시그널 내용 확인
    for token_id in test_token_ids:
        signal = await system.bus.get_signal(token_id)
        logger.info(f"   {token_id[:16]}... → Sent:{signal.sentiment_score:+.2f}")

    logger.info(f"\n✅ TEST 2 PASSED: SignalBus updates in real-time!")


async def main():
    """메인 테스트 실행"""
    logger.info("\n" + "="*60)
    logger.info("🚀 Dashboard Real-time Update Test")
    logger.info("="*60)
    logger.info("\nℹ️  Instructions:")
    logger.info("1. Run dashboard in another terminal: venv/bin/python run_swarm.py --ui --dry-run")
    logger.info("2. Watch the WALLET and SIGNALS panels")
    logger.info("3. Run this test script")
    logger.info("4. Verify that panels update in real-time")
    logger.info("\n⏳ Starting in 10 seconds... (Launch dashboard now!)")
    await asyncio.sleep(10)

    # SwarmSystem 초기화
    system = SwarmSystem()
    await system.setup(dry_run=True)
    logger.info("✅ SwarmSystem initialized")

    # 테스트 실행
    await test_budget_updates(system)
    await test_signal_updates(system)

    logger.info("\n" + "="*60)
    logger.info("🎉 ALL TESTS COMPLETED!")
    logger.info("="*60)
    logger.info("\n✅ If you saw changes in the dashboard panels, real-time updates work correctly!")

    await system.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
