from sqlalchemy import event, Integer, select, testing
from sqlalchemy.ext import linter
from sqlalchemy.ext.linter import find_unmatching_froms
from sqlalchemy.testing import expect_warnings, fixtures, eq_
from sqlalchemy.testing.mock import patch
from sqlalchemy.testing.schema import Column, Table


class TestFindUnmatchingFroms(fixtures.TablesTest):
    @classmethod
    def define_tables(cls, metadata):
        Table("table_a", metadata, Column("col_a", Integer, primary_key=True))
        Table("table_b", metadata, Column("col_b", Integer, primary_key=True))
        Table("table_c", metadata, Column("col_c", Integer, primary_key=True))
        Table("table_d", metadata, Column("col_d", Integer, primary_key=True))

    def setup(self):
        self.a = self.tables.table_a
        self.b = self.tables.table_b
        self.c = self.tables.table_c
        self.d = self.tables.table_d

    def test_everything_is_connected(self):
        query = (
            select([self.a])
            .select_from(self.a.join(self.b, self.a.c.col_a == self.b.c.col_b))
            .select_from(self.c)
            .select_from(self.d)
            .where(self.d.c.col_d == self.b.c.col_b)
            .where(self.c.c.col_c == self.d.c.col_d)
            .where(self.c.c.col_c == 5)
        )
        froms, start = find_unmatching_froms(query)
        assert not froms

        for start in self.a, self.b, self.c, self.d:
            froms, start = find_unmatching_froms(query, start)
            assert not froms

    def test_plain_cartesian(self):
        query = (
            select([self.a])
            .where(self.b.c.col_b == 5)
        )
        froms, start = find_unmatching_froms(query, self.a)
        eq_(start, self.a)
        eq_(froms, {self.b})

        froms, start = find_unmatching_froms(query, self.b)
        eq_(start, self.b)
        eq_(froms, {self.a})

    def test_disconnect_between_ab_cd(self):
        query = (
            select([self.a])
            .select_from(self.a.join(self.b, self.a.c.col_a == self.b.c.col_b))
            .select_from(self.c)
            .select_from(self.d)
            .where(self.c.c.col_c == self.d.c.col_d)
            .where(self.c.c.col_c == 5)
        )
        for start in self.a, self.b:
            froms, start = find_unmatching_froms(query, start)
            eq_(start, start)
            eq_(froms, {self.c, self.d})
        for start in self.c, self.d:
            froms, start = find_unmatching_froms(query, start)
            eq_(start, start)
            eq_(froms, {self.a, self.b})

    def test_c_and_d_both_disconnected(self):
        query = (
            select([self.a])
            .select_from(self.a.join(self.b, self.a.c.col_a == self.b.c.col_b))
            .where(self.c.c.col_c == 5)
            .where(self.d.c.col_d == 10)
        )
        for start in self.a, self.b:
            froms, start = find_unmatching_froms(query, start)
            eq_(start, start)
            eq_(froms, {self.c, self.d})

        froms, start = find_unmatching_froms(query, self.c)
        eq_(start, self.c)
        eq_(froms, {self.a, self.b, self.d})

        froms, start = find_unmatching_froms(query, self.d)
        eq_(start, self.d)
        eq_(froms, {self.a, self.b, self.c})

    def test_now_connected(self):
        query = (
            select([self.a])
            .select_from(self.a.join(self.b, self.a.c.col_a == self.b.c.col_b))
            .select_from(self.c.join(self.d, self.c.c.col_c == self.d.c.col_d))
            .where(self.c.c.col_c == self.b.c.col_b)
            .where(self.c.c.col_c == 5)
            .where(self.d.c.col_d == 10)
        )
        froms, start = find_unmatching_froms(query)
        assert not froms

        for start in self.a, self.b, self.c, self.d:
            froms, start = find_unmatching_froms(query, start)
            assert not froms

    def test_disconnected_subquery(self):
        subq = (
            select([self.a])
            .where(self.a.c.col_a == self.b.c.col_b)
            .subquery()
        )
        stmt = select([self.c]).select_from(subq)

        froms, start = find_unmatching_froms(stmt, self.c)
        eq_(start, self.c)
        eq_(froms, {subq})

        froms, start = find_unmatching_froms(stmt, subq)
        eq_(start, subq)
        eq_(froms, {self.c})

    def test_now_connect_it(self):
        subq = (
            select([self.a])
            .where(self.a.c.col_a == self.b.c.col_b)
            .subquery()
        )
        stmt = (
            select([self.c])
            .select_from(subq)
            .where(self.c.c.col_c == subq.c.col_a)
        )

        froms, start = find_unmatching_froms(stmt)
        assert not froms

        for start in self.c, subq:
            froms, start = find_unmatching_froms(stmt, start)
            assert not froms

    def test_right_nested_join_without_issue(self):
        query = (
            select([self.a])
            .select_from(
                self.a.join(
                    self.b.join(self.c, self.b.c.col_b == self.c.c.col_c),
                    self.a.c.col_a == self.b.c.col_b,
                )
            )
        )
        froms, start = find_unmatching_froms(query)
        assert not froms

        for start in self.a, self.b, self.c:
            froms, start = find_unmatching_froms(query, start)
            assert not froms

    def test_right_nested_join_with_an_issue(self):
        query = (
            select([self.a])
            .select_from(
                self.a.join(
                    self.b.join(self.c, self.b.c.col_b == self.c.c.col_c),
                    self.a.c.col_a == self.b.c.col_b,
                ),
            )
            .where(self.d.c.col_d == 5)
        )

        for start in self.a, self.b, self.c:
            froms, start = find_unmatching_froms(query, start)
            eq_(start, start)
            eq_(froms, {self.d})

        froms, start = find_unmatching_froms(query, self.d)
        eq_(start, self.d)
        eq_(froms, {self.a, self.b, self.c})

    def test_no_froms(self):
        query = (select([1]))

        froms, start = find_unmatching_froms(query)
        assert not froms


class TestLinter(fixtures.TablesTest):
    @classmethod
    def define_tables(cls, metadata):
        Table("table_a", metadata, Column("col_a", Integer, primary_key=True))
        Table("table_b", metadata, Column("col_b", Integer, primary_key=True))
        Table("table_c", metadata, Column("col_c", Integer, primary_key=True))
        Table("table_d", metadata, Column("col_d", Integer, primary_key=True))

    def setup(self):
        self.a = self.tables.table_a
        self.b = self.tables.table_b
        self.c = self.tables.table_c
        self.d = self.tables.table_d
        event.listen(testing.db, 'before_execute', linter.before_execute_hook)

    def test_noop_for_unhandled_objects(self):
        with testing.db.connect() as conn:
            conn.execute('SELECT 1;').fetchone()

    def test_does_not_modify_query(self):
        with testing.db.connect() as conn:
            [result] = conn.execute(select([1])).fetchone()
            eq_(result, 1)

    def test_integration(self):
        query = (
            select([self.a.c.col_a])
            .where(self.b.c.col_b == 5)
        )

        def deterministic_find_unmatching_froms(query):
            return find_unmatching_froms(query, start_with=self.a)

        with patch(
            'sqlalchemy.ext.linter.find_unmatching_froms',
            autospec=True,
            side_effect=deterministic_find_unmatching_froms,
        ) as m:
            with expect_warnings(
                r"Query.*Select table_a\.col_a.*has FROM elements.*table_b.*"
                r"that are not joined up to FROM element.*table_a.*"
            ):
                with testing.db.connect() as conn:
                    conn.execute(query)
            m.assert_called_once_with(query)

    def teardown(self):
        event.remove(testing.db, 'before_execute', linter.before_execute_hook)