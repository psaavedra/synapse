from tests import unittest
from mock import patch

from synapse.util.caches.stream_change_cache import StreamChangeCache


class StreamChangeCacheTests(unittest.TestCase):
    """
    Tests for StreamChangeCache.
    """

    def test_prefilled_cache(self):
        """
        Providing a prefilled cache to StreamChangeCache will result in a cache
        with the prefilled-cache entered in.
        """
        cache = StreamChangeCache("#test", 1, prefilled_cache={"user@foo.com": 2})
        self.assertTrue(cache.has_entity_changed("user@foo.com", 1))

    def test_has_entity_changed(self):
        """
        StreamChangeCache.entity_has_changed will mark entities as changed, and
        has_entity_changed will observe the changed entities.
        """
        cache = StreamChangeCache("#test", 3)

        cache.entity_has_changed("user@foo.com", 6)
        cache.entity_has_changed("bar@baz.net", 7)

        # If it's been changed after that stream position, return True
        self.assertTrue(cache.has_entity_changed("user@foo.com", 4))
        self.assertTrue(cache.has_entity_changed("bar@baz.net", 4))

        # If it's been changed at that stream position, return False
        self.assertFalse(cache.has_entity_changed("user@foo.com", 6))

        # If there's no changes after that stream position, return False
        self.assertFalse(cache.has_entity_changed("user@foo.com", 7))

        # If the entity does not exist, return False.
        self.assertFalse(cache.has_entity_changed("not@here.website", 7))

        # If we request before the stream cache's earliest known position,
        # return True, whether it's a known entity or not.
        self.assertTrue(cache.has_entity_changed("user@foo.com", 0))
        self.assertTrue(cache.has_entity_changed("not@here.website", 0))

    @patch("synapse.util.caches.CACHE_SIZE_FACTOR", 1.0)
    def test_has_entity_changed_pops_off_start(self):
        """
        StreamChangeCache.entity_has_changed will respect the max size and
        purge the oldest items upon reaching that max size.
        """
        cache = StreamChangeCache("#test", 1, max_size=2)

        cache.entity_has_changed("user@foo.com", 2)
        cache.entity_has_changed("bar@baz.net", 3)
        cache.entity_has_changed("user@elsewhere.org", 4)

        # The cache is at the max size, 2
        self.assertEqual(len(cache._cache), 2)

        # The oldest item has been popped off
        self.assertTrue("user@foo.com" not in cache._entity_to_key)

        # If we update an existing entity, it keeps the two existing entities
        cache.entity_has_changed("bar@baz.net", 5)
        self.assertEqual(
            set(["bar@baz.net", "user@elsewhere.org"]), set(cache._entity_to_key)
        )

    def test_get_all_entities_changed(self):
        """
        StreamChangeCache.get_all_entities_changed will return all changed
        entities since the given position.  If the position is before the start
        of the known stream, it returns None instead.
        """
        cache = StreamChangeCache("#test", 1)

        cache.entity_has_changed("user@foo.com", 2)
        cache.entity_has_changed("bar@baz.net", 3)
        cache.entity_has_changed("user@elsewhere.org", 4)

        self.assertEqual(
            cache.get_all_entities_changed(1),
            ["user@foo.com", "bar@baz.net", "user@elsewhere.org"],
        )
        self.assertEqual(
            cache.get_all_entities_changed(2), ["bar@baz.net", "user@elsewhere.org"]
        )
        self.assertEqual(cache.get_all_entities_changed(3), ["user@elsewhere.org"])
        self.assertEqual(cache.get_all_entities_changed(0), None)

    def test_has_any_entity_changed(self):
        """
        StreamChangeCache.has_any_entity_changed will return True if any
        entities have been changed since the provided stream position, and
        False if they have not.  If the cache has entries and the provided
        stream position is before it, it will return True, otherwise False if
        the cache has no entries.
        """
        cache = StreamChangeCache("#test", 1)

        # With no entities, it returns False for the past, present, and future.
        self.assertFalse(cache.has_any_entity_changed(0))
        self.assertFalse(cache.has_any_entity_changed(1))
        self.assertFalse(cache.has_any_entity_changed(2))

        # We add an entity
        cache.entity_has_changed("user@foo.com", 2)

        # With an entity, it returns True for the past, the stream start
        # position, and False for the stream position the entity was changed
        # on and ones after it.
        self.assertTrue(cache.has_any_entity_changed(0))
        self.assertTrue(cache.has_any_entity_changed(1))
        self.assertFalse(cache.has_any_entity_changed(2))
        self.assertFalse(cache.has_any_entity_changed(3))

    def test_get_entities_changed(self):
        """
        StreamChangeCache.get_entities_changed will return the entities in the
        given list that have changed since the provided stream ID.  If the
        stream position is earlier than the earliest known position, it will
        return all of the entities queried for.
        """
        cache = StreamChangeCache("#test", 1)

        cache.entity_has_changed("user@foo.com", 2)
        cache.entity_has_changed("bar@baz.net", 3)
        cache.entity_has_changed("user@elsewhere.org", 4)

        # Query all the entries, but mid-way through the stream. We should only
        # get the ones after that point.
        self.assertEqual(
            cache.get_entities_changed(
                ["user@foo.com", "bar@baz.net", "user@elsewhere.org"], stream_pos=2
            ),
            set(["bar@baz.net", "user@elsewhere.org"]),
        )

        # Query all the entries mid-way through the stream, but include one
        # that doesn't exist in it. We should get back the one that doesn't
        # exist, too.
        self.assertEqual(
            cache.get_entities_changed(
                [
                    "user@foo.com",
                    "bar@baz.net",
                    "user@elsewhere.org",
                    "not@here.website",
                ],
                stream_pos=2,
            ),
            set(["bar@baz.net", "user@elsewhere.org", "not@here.website"]),
        )

        # Query all the entries, but before the first known point. We will get
        # all the entries we queried for, including ones that don't exist.
        self.assertEqual(
            cache.get_entities_changed(
                [
                    "user@foo.com",
                    "bar@baz.net",
                    "user@elsewhere.org",
                    "not@here.website",
                ],
                stream_pos=0,
            ),
            set(
                [
                    "user@foo.com",
                    "bar@baz.net",
                    "user@elsewhere.org",
                    "not@here.website",
                ]
            ),
        )

    def test_max_pos(self):
        """
        StreamChangeCache.get_max_pos_of_last_change will return the most
        recent point where the entity could have changed.  If the entity is not
        known, the stream start is provided instead.
        """
        cache = StreamChangeCache("#test", 1)

        cache.entity_has_changed("user@foo.com", 2)
        cache.entity_has_changed("bar@baz.net", 3)
        cache.entity_has_changed("user@elsewhere.org", 4)

        # Known entities will return the point where they were changed.
        self.assertEqual(cache.get_max_pos_of_last_change("user@foo.com"), 2)
        self.assertEqual(cache.get_max_pos_of_last_change("bar@baz.net"), 3)
        self.assertEqual(cache.get_max_pos_of_last_change("user@elsewhere.org"), 4)

        # Unknown entities will return the stream start position.
        self.assertEqual(cache.get_max_pos_of_last_change("not@here.website"), 1)
