# tests/rhosocial/activerecord_bigquery_test/feature/query/joins/test_join_on_params.py
"""Tests for the on_params parameter in JOIN methods (sync and async)."""

from decimal import Decimal

import pytest


class TestSyncJoinOnParams:
    """Synchronous JOIN with on_params tests."""

    def test_inner_join_with_on_params(self, order_fixtures):
        """Test inner_join with a string ON condition and on_params."""
        User, Order, OrderItem = order_fixtures

        user = User(username="on_params_user", email="op@example.com", age=30)
        user.save()

        order = Order(user_id=user.id, order_number="OP-001", total_amount=Decimal("100.00"))
        order.save()

        results = (
            Order.query()
            .inner_join(
                User,
                on='"user_id" = ?',
                on_params=[user.id],
            )
            .where(Order.c.id == order.id)
            .all()
        )

        assert len(results) >= 1

    def test_left_join_with_on_params(self, order_fixtures):
        """Test left_join with a string ON condition and on_params."""
        User, Order, OrderItem = order_fixtures

        user = User(username="left_op_user", email="lop@example.com", age=30)
        user.save()

        order = Order(user_id=user.id, order_number="LOP-001", total_amount=Decimal("50.00"))
        order.save()

        results = (
            Order.query()
            .left_join(
                User,
                on='"user_id" = ?',
                on_params=[user.id],
            )
            .where(Order.c.id == order.id)
            .all()
        )

        assert len(results) >= 1

    def test_join_with_on_params_and_alias(self, order_fixtures):
        """Test join with on_params and table alias."""
        User, Order, OrderItem = order_fixtures

        user = User(username="alias_op_user", email="aop@example.com", age=30)
        user.save()

        order = Order(user_id=user.id, order_number="AOP-001", total_amount=Decimal("120.00"))
        order.save()

        results = (
            Order.query()
            .inner_join(
                User,
                on='"user_id" = ?',
                on_params=[user.id],
                alias="u",
            )
            .where(Order.c.id == order.id)
            .all()
        )

        assert len(results) >= 1

    def test_join_with_on_params_none_and_no_placeholders(self, order_fixtures):
        """Test join with on_params=None when string ON has no placeholders."""
        User, Order, OrderItem = order_fixtures

        user = User(username="nop_op_user", email="nop@example.com", age=30)
        user.save()

        order = Order(user_id=user.id, order_number="NOP-001", total_amount=Decimal("80.00"))
        order.save()

        # Use a string ON condition without placeholders so on_params=None is valid
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            results = (
                Order.query()
                .inner_join(
                    User,
                    on='"user_id" = "users"."id"',
                    on_params=None,
                )
                .where(Order.c.id == order.id)
                .all()
            )

        assert len(results) >= 1

    def test_join_with_multiple_on_params(self, order_fixtures):
        """Test join with multiple on_params values."""
        User, Order, OrderItem = order_fixtures

        user = User(username="multi_op_user", email="mop@example.com", age=30)
        user.save()

        order = Order(user_id=user.id, order_number="MOP-001", total_amount=Decimal("100.00"), status="active")
        order.save()

        results = (
            Order.query()
            .inner_join(
                User,
                on='"user_id" = ? AND "status" = ?',
                on_params=[user.id, "active"],
            )
            .where(Order.c.id == order.id)
            .all()
        )

        assert len(results) >= 1


class TestAsyncJoinOnParams:
    """Asynchronous JOIN with on_params tests."""

    @pytest.mark.asyncio
    async def test_async_inner_join_with_on_params(self, async_order_fixtures):
        """Test async inner_join with a string ON condition and on_params."""
        AsyncUser, AsyncOrder, AsyncOrderItem = async_order_fixtures

        user = AsyncUser(username="async_op_user", email="aop@example.com", age=30)
        await user.save()

        order = AsyncOrder(user_id=user.id, order_number="AOP-001", total_amount=Decimal("100.00"))
        await order.save()

        results = (
            await AsyncOrder.query()
            .inner_join(
                AsyncUser,
                on='"user_id" = ?',
                on_params=[user.id],
            )
            .where(AsyncOrder.c.id == order.id)
            .all()
        )

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_async_left_join_with_on_params(self, async_order_fixtures):
        """Test async left_join with a string ON condition and on_params."""
        AsyncUser, AsyncOrder, AsyncOrderItem = async_order_fixtures

        user = AsyncUser(username="async_lop_user", email="alop@example.com", age=30)
        await user.save()

        order = AsyncOrder(user_id=user.id, order_number="ALOP-001", total_amount=Decimal("50.00"))
        await order.save()

        results = (
            await AsyncOrder.query()
            .left_join(
                AsyncUser,
                on='"user_id" = ?',
                on_params=[user.id],
            )
            .where(AsyncOrder.c.id == order.id)
            .all()
        )

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_async_join_with_on_params_and_alias(self, async_order_fixtures):
        """Test async join with on_params and table alias."""
        AsyncUser, AsyncOrder, AsyncOrderItem = async_order_fixtures

        user = AsyncUser(username="async_aop_user", email="aaop@example.com", age=30)
        await user.save()

        order = AsyncOrder(user_id=user.id, order_number="AAOP-001", total_amount=Decimal("120.00"))
        await order.save()

        results = (
            await AsyncOrder.query()
            .inner_join(
                AsyncUser,
                on='"user_id" = ?',
                on_params=[user.id],
                alias="u",
            )
            .where(AsyncOrder.c.id == order.id)
            .all()
        )

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_async_join_with_multiple_on_params(self, async_order_fixtures):
        """Test async join with multiple on_params values."""
        AsyncUser, AsyncOrder, AsyncOrderItem = async_order_fixtures

        user = AsyncUser(username="async_mop_user", email="amop@example.com", age=30)
        await user.save()

        order = AsyncOrder(user_id=user.id, order_number="AMOP-001", total_amount=Decimal("100.00"), status="active")
        await order.save()

        results = (
            await AsyncOrder.query()
            .inner_join(
                AsyncUser,
                on='"user_id" = ? AND "status" = ?',
                on_params=[user.id, "active"],
            )
            .where(AsyncOrder.c.id == order.id)
            .all()
        )

        assert len(results) >= 1
