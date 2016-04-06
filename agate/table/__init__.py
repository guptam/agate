#!/usr/bin/env python

"""
The :class:`.Table` object is the most important class agate. Tables are
created by supplying row data, column names and subclasses of :class:`.DataType`
to the constructor. Once created, the data in a table **can not be changed**.
This concept is central to agate.

Instead of modifying the data, various methods can be used to create new,
derivative tables. For example, the :meth:`.Table.select` method creates a new
table with only the specified columns. The :meth:`.Table.where` method creates
a new table with only those rows that pass a test. And :meth:`.Table.order_by`
creates a sorted table. In all of these cases the output is new :class:`.Table`
and the existing table remains unmodified.

Tables are not themselves iterable, but the columns of the table can be
accessed via :attr:`.Table.columns` and the rows via :attr:`.Table.rows`. Both
sequences can be accessed either by numeric index or by name. (In the case of
rows, row names are optional.)
"""

from itertools import chain
import sys
import warnings

import six
from six.moves import range, zip  # pylint: disable=W0622

from agate.columns import Column
from agate.data_types import DataType
from agate.mapped_sequence import MappedSequence
from agate.rows import Row
from agate.type_tester import TypeTester
from agate import utils
from agate.warns import warn_duplicate_column
from agate.utils import allow_tableset_proxy


@six.python_2_unicode_compatible
class Table(utils.Patchable):
    """
    A dataset consisting of rows and columns. Columns refer to "vertical" slices
    of data that must all be of the same type. Rows refer to "horizontal" slices
    of data that may (and usually do) contain mixed types.

    The sequence of :class:`.Column` instances are retrieved via the
    :attr:`.Table.columns` property. They may be accessed by either numeric
    index or by unique column name.

    The sequence of :class:`.Row` instances are retrieved via the
    :attr:`.Table.rows` property. They maybe be accessed by either numeric index
    or, if specified, unique row names.

    :param rows:
        The data as a sequence of any sequences: tuples, lists, etc. If
        any row has fewer values than the number of columns, it will be filled
        out with nulls. No row may have more values than the number of columns.
    :param column_names:
        A sequence of string names for each column or `None`, in which case
        column names will be automatically assigned using :func:`.letter_name`.
    :param column_types:
        A sequence of instances of :class:`.DataType` or an instance of
        :class:`.TypeTester` or `None` in which case a generic TypeTester will
        be used. Alternatively, a dictionary with column names as keys and
        instances of :class:`.DataType` as values to specify some types.
    :param row_names:
        Specifies unique names for each row. This parameter is
        optional. If specified it may be 1) the name of a single column that
        contains a unique identifier for each row, 2) a key function that takes
        a :class:`.Row` and returns a unique identifier or 3) a sequence of
        unique identifiers of the same length as the sequence of rows. The
        uniqueness of resulting identifiers is not validated, so be certain
        the values you provide are truly unique.
    :param _is_fork:
        Used internally to skip certain validation steps when data
        is propagated from an existing table. When :code:`True`, rows are
        assumed to be :class:`.Row` instances, rather than raw data.
    """
    def __init__(self, rows, column_names=None, column_types=None, row_names=None, _is_fork=False):
        if isinstance(rows, six.string_types):
            raise ValueError('When created directly, the first argument to Table must be a sequence of rows. Did you want agate.Table.from_csv?')

        # Validate column names
        if column_names:
            final_column_names = []

            for i, column_name in enumerate(column_names):
                if column_name is None:
                    new_column_name = utils.letter_name(i)
                    warnings.warn('Column name not specified. "%s" will be used as name.' % new_column_name, RuntimeWarning)
                elif isinstance(column_name, six.string_types):
                    new_column_name = column_name
                else:
                    raise ValueError('Column names must be strings or None.')

                final_column_name = new_column_name
                duplicates = 0
                while final_column_name in final_column_names:
                    final_column_name = new_column_name + '_' + str(duplicates + 2)
                    duplicates += 1

                if duplicates > 0:
                    warn_duplicate_column(new_column_name, final_column_name)

                final_column_names.append(final_column_name)

            self._column_names = tuple(final_column_names)
        elif rows:
            self._column_names = tuple(utils.letter_name(i) for i in range(len(rows[0])))
            warnings.warn('Column names not specified. "%s" will be used as names.' % str(self._column_names), RuntimeWarning, stacklevel=2)
        else:
            self._column_names = []

        len_column_names = len(self._column_names)

        # Validate column_types
        if column_types is None:
            column_types = TypeTester()
        elif isinstance(column_types, dict):
            for v in column_types.values():
                if not isinstance(v, DataType):
                    raise ValueError('Column types must be instances of DataType.')

            column_types = TypeTester(force=column_types)
        elif not isinstance(column_types, TypeTester):
            for column_type in column_types:
                if not isinstance(column_type, DataType):
                    raise ValueError('Column types must be instances of DataType.')

        if isinstance(column_types, TypeTester):
            self._column_types = column_types.run(rows, self._column_names)
        else:
            self._column_types = tuple(column_types)

        if len_column_names != len(self._column_types):
            raise ValueError('column_names and column_types must be the same length.')

        if not _is_fork:
            new_rows = []
            cast_funcs = [c.cast for c in self._column_types]

            for i, row in enumerate(rows):
                len_row = len(row)

                if len_row > len_column_names:
                    raise ValueError('Row %i has %i values, but Table only has %i columns.' % (i, len_row, len_column_names))
                elif len(row) < len_column_names:
                    row = chain(row, [None] * (len(self.column_names) - len_row))

                new_rows.append(Row((cast_funcs[i](d) for i, d in enumerate(row)), self._column_names))
        else:
            new_rows = rows

        if row_names:
            computed_row_names = []

            if isinstance(row_names, six.string_types):
                for row in new_rows:
                    name = row[row_names]
                    computed_row_names.append(name)
            elif hasattr(row_names, '__call__'):
                for row in new_rows:
                    name = row_names(row)
                    computed_row_names.append(name)
            elif utils.issequence(row_names):
                computed_row_names = row_names
            else:
                raise ValueError('row_names must be a column name, function or sequence')

            for row_name in computed_row_names:
                if isinstance(row_name, int):
                    raise ValueError('Row names cannot be of type int. Use Decimal for numbered row names.')

            self._row_names = tuple(computed_row_names)
        else:
            self._row_names = None

        self._rows = MappedSequence(new_rows, self._row_names)

        # Build columns
        new_columns = []

        for i, (name, data_type) in enumerate(zip(self._column_names, self._column_types)):
            column = Column(i, name, data_type, self._rows, row_names=self._row_names)
            new_columns.append(column)

        self._columns = MappedSequence(new_columns, self._column_names)

    def __str__(self):
        """
        Print the table's structure using :meth:`.Table.print_structure`.
        """
        structure = six.StringIO()

        self.print_structure(output=structure)

        return structure.getvalue()

    @property
    def column_types(self):
        """
        An tuple :class:`.DataType` instances.
        """
        return self._column_types

    @property
    def column_names(self):
        """
        An tuple of strings.
        """
        return self._column_names

    @property
    def row_names(self):
        """
        An tuple of strings, if this table has row names.

        If this table does not have row names, then :code:`None`.
        """
        return self._row_names

    @property
    def columns(self):
        """
        A :class:`.MappedSequence` with column names for keys and
        :class:`.Column` instances for values.
        """
        return self._columns

    @property
    def rows(self):
        """
        A :class:`.MappedSeqeuence` with row names for keys (if specified) and
        :class:`.Row` instances for values.
        """
        return self._rows

    def _fork(self, rows, column_names=None, column_types=None, row_names=None):
        """
        Create a new table using the metadata from this one.

        This method is used internally by functions like
        :meth:`.Table.order_by`.

        :param rows:
            Row data for the forked table.
        :param column_names:
            Column names for the forked table. If not specified, fork will use
            this table's column names.
        :param column_types:
            Column types for the forked table. If not specified, fork will use
            this table's column names.
        :param row_names:
            Row names for the forked table. If not specified, fork will use
            this table's row names.
        """
        if column_names is None:
            column_names = self._column_names

        if column_types is None:
            column_types = self._column_types

        if row_names is None:
            row_names = self._row_names

        return Table(rows, column_names, column_types, row_names=row_names, _is_fork=True)

    def rename(self, column_names=None, row_names=None):
        """
        Create a copy of this table with different column names or row names.

        :param column_names:
            New column names for the renamed table. May be either an array or
            a dictionary mapping existing column names to new names. If not
            specified, will use this table's existing column names.
        :param row_names:
            New row names for the renamed table. May be either an array or
            a dictionary mapping existing row names to new names. If not
            specified, will use this table's existing row names.
        """
        if isinstance(column_names, dict):
            column_names = [column_names[name] if name in column_names else name for name in self.column_names]

        if isinstance(row_names, dict):
            row_names = [row_names[name] if name in row_names else name for name in self.row_names]

        if column_names is not None and column_names != self.column_names:
            if row_names is None:
                row_names = self._row_names

            return Table(self.rows, column_names, self.column_types, row_names=row_names, _is_fork=False)
        else:
            return self._fork(self.rows, column_names, self._column_types, row_names=row_names)

    @allow_tableset_proxy
    def select(self, key):
        """
        Create a new table with only the specified columns.

        :param key:
            Either the name of a single column to include or a sequence of such
            names.
        :returns:
            A new :class:`.Table`.
        """
        if not utils.issequence(key):
            key = [key]

        column_types = [self.columns[name].data_type for name in key]
        new_rows = []

        for row in self._rows:
            new_rows.append(Row(tuple(row[n] for n in key), key))

        return self._fork(new_rows, key, column_types)

    @allow_tableset_proxy
    def exclude(self, key):
        """
        Create a new table without the specified columns.

        :param key:
            Either the name of a single column to exclude or a sequence of such
            names.
        :returns:
            A new :class:`.Table`.
        """
        if not utils.issequence(key):
            key = [key]

        selected_column_names = [n for n in self._column_names if n not in key]

        return self.select(selected_column_names)

    @allow_tableset_proxy
    def where(self, test):
        """
        Create a new :class:`.Table` with only those rows that pass a test.

        :param test:
            A function that takes a :class:`.Row` and returns :code:`True` if
            it should be included in the new :class:`.Table`.
        :type test:
            :class:`function`
        :returns:
            A new :class:`.Table`.
        """
        rows = []

        if self._row_names is not None:
            row_names = []
        else:
            row_names = None

        for i, row in enumerate(self._rows):
            if test(row):
                rows.append(row)

                if self._row_names is not None:
                    row_names.append(self._row_names[i])

        return self._fork(rows, row_names=row_names)

    @allow_tableset_proxy
    def find(self, test):
        """
        Find the first row that passes test.

        :param test:
            A function that takes a :class:`.Row` and returns :code:`True` if
            it matches.
        :type test:
            :class:`function`
        :returns:
            A single :class:`.Row` if found, or `None`.
        """
        for row in self._rows:
            if test(row):
                return row

        return None

    @allow_tableset_proxy
    def order_by(self, key, reverse=False):
        """
        Create a new table that is sorted.

        :param key:
            Either the name of a single column to sort by, a sequence of such
            names, or a :class:`function` that takes a row and returns a value
            to sort by.
        :param reverse:
            If `True` then sort in reverse (typically, descending) order.
        :returns:
            A new :class:`.Table`.
        """
        if len(self._rows) == 0:
            return self._fork(self._rows)
        else:
            key_is_row_function = hasattr(key, '__call__')
            key_is_sequence = utils.issequence(key)

            def sort_key(data):
                row = data[1]

                if key_is_row_function:
                    k = key(row)
                elif key_is_sequence:
                    k = tuple(row[n] for n in key)
                else:
                    k = row[key]

                if k is None:
                    return utils.NullOrder()

                return k

            results = sorted(enumerate(self._rows), key=sort_key, reverse=reverse)

            indices, rows = zip(*results)

            if self._row_names is not None:
                row_names = [self._row_names[i] for i in indices]
            else:
                row_names = None

            return self._fork(rows, row_names=row_names)

    @allow_tableset_proxy
    def limit(self, start_or_stop=None, stop=None, step=None):
        """
        Create a new table with fewer rows.

        See also: Python's builtin :func:`slice`.

        :param start_or_stop:
            If the only argument, then how many rows to include, otherwise,
            the index of the first row to include.
        :param stop:
            The index of the last row to include.
        :param step:
            The size of the jump between rows to include. (`step=2` will return
            every other row.)
        :returns:
            A new :class:`.Table`.
        """
        if stop or step:
            s = slice(start_or_stop, stop, step)
        else:
            s = slice(start_or_stop)
        rows = self._rows[s]

        if self._row_names is not None:
            row_names = self._row_names[s]
        else:
            row_names = None

        return self._fork(rows, row_names=row_names)

    @allow_tableset_proxy
    def distinct(self, key=None):
        """
        Create a new table with only unique rows.

        :param key:
            Either the name of a single column to use to identify unique rows, a
            sequence of such column names, a :class:`function` that takes a
            row and returns a value to identify unique rows, or `None`, in
            which case the entire row will be checked for uniqueness.
        :returns:
            A new :class:`.Table`.
        """
        key_is_row_function = hasattr(key, '__call__')
        key_is_sequence = utils.issequence(key)

        uniques = []
        rows = []

        if self._row_names is not None:
            row_names = []
        else:
            row_names = None

        for i, row in enumerate(self._rows):
            if key_is_row_function:
                k = key(row)
            elif key_is_sequence:
                k = (row[j] for j in key)
            elif key is None:
                k = tuple(row)
            else:
                k = row[key]

            if k not in uniques:
                uniques.append(k)
                rows.append(row)

                if self._row_names is not None:
                    row_names.append(self._row_names[i])

        return self._fork(rows, row_names=row_names)

    def print_csv(self, **kwargs):
        """
        Print this table as a CSV.

        This is the same as passing :code:`sys.stdout` to :meth:`.Table.to_csv`.

        :code:`kwargs` will be passed on to :meth:`.Table.to_csv`.
        """
        self.to_csv(sys.stdout, **kwargs)

    def print_json(self, **kwargs):
        """
        Print this table as JSON.

        This is the same as passing :code:`sys.stdout` to
        :meth:`.Table.to_json`.

        :code:`kwargs` will be passed on to :meth:`.Table.to_json`.
        """
        self.to_json(sys.stdout, **kwargs)


from agate.table.aggregate import aggregate
from agate.table.bins import bins
from agate.table.compute import compute
from agate.table.denormalize import denormalize
from agate.table.from_csv import from_csv
from agate.table.from_fixed import from_fixed
from agate.table.from_json import from_json
from agate.table.from_object import from_object
from agate.table.group_by import group_by
from agate.table.homogenize import homogenize
from agate.table.join import join
from agate.table.merge import merge
from agate.table.normalize import normalize
from agate.table.pivot import pivot
from agate.table.print_bars import print_bars
from agate.table.print_html import print_html
from agate.table.print_structure import print_structure
from agate.table.print_table import print_table
from agate.table.to_csv import to_csv
from agate.table.to_json import to_json

Table.aggregate = aggregate
Table.bins = bins
Table.compute = compute
Table.denormalize = denormalize
Table.from_csv = from_csv
Table.from_fixed = from_fixed
Table.from_json = from_json
Table.from_object = from_object
Table.group_by = group_by
Table.homogenize = homogenize
Table.join = join
Table.merge = merge
Table.normalize = normalize
Table.pivot = pivot
Table.print_bars = print_bars
Table.print_html = print_html
Table.print_structure = print_structure
Table.print_table = print_table
Table.to_csv = to_csv
Table.to_json = to_json
