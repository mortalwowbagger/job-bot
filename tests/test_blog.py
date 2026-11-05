"""Blog: safe rendering, and nothing public until checked + launched."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from jobbot import blog
from jobbot.cloud.store import MemoryStore
from jobbot.cloud.webapp import create_app

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())

POST = """---
title: Stop retyping your work history
description: Why ATS forms ask for it twice, and how to fill them faster.
date: 2026-11-20
checked: {checked}
---
# Intro
Most **ATS** forms ask for your *work history* again. See [job-bot](/) or [docs](https://example.com).

- one
- two

<script>alert(1)</script> and [bad](javascript:alert(1))
"""


class TestBlog(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(blog, "PUBLISHED", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, checked):
        (self.dir / f"{name}.md").write_text(POST.format(checked=checked))

    def client(self, launched):
        return create_app(MemoryStore(), lambda t: {}, lambda u: None,
                          cloud_cfg={**CFG["cloud"], "launched": launched}).test_client()

    def test_rendering_is_safe(self):
        html = blog.render_markdown(blog.parse(POST.format(checked="true"))[1])
        self.assertIn("<h2>Intro</h2>", html)                     # page title is the only h1
        self.assertIn("<b>ATS</b>", html)
        self.assertIn("<i>work history</i>", html)
        self.assertIn('<a href="/">job-bot</a>', html)
        self.assertIn('rel="noopener" target="_blank">docs</a>', html)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('href="javascript', html)

    def test_nothing_public_before_launch(self):
        self.write("stop-retyping", "true")
        c = self.client(launched=False)
        self.assertEqual(c.get("/blog").status_code, 404)
        self.assertEqual(c.get("/blog/stop-retyping").status_code, 404)

    def test_only_checked_articles_after_launch(self):
        self.write("stop-retyping", "true")
        self.write("unchecked-draft", "false")
        c = self.client(launched=True)
        r = c.get("/blog/stop-retyping")
        self.assertEqual(r.status_code, 200)
        self.assertIn('"@type": "Article"', r.data.decode())
        self.assertEqual(c.get("/blog/unchecked-draft").status_code, 404)
        self.assertNotIn("unchecked-draft", c.get("/blog").data.decode())
        self.assertIn("/blog/stop-retyping", c.get("/sitemap.xml").data.decode())
        self.assertNotIn("unchecked", c.get("/sitemap.xml").data.decode())

    def test_problems_flag_unverifiable_claims(self):
        issues = blog.problems({"description": "x" * 200, "date": "Nov 20",
                                "body_md": "Get 3x more interviews. We guarantee results."})
        self.assertTrue(any("155" in i for i in issues))
        self.assertTrue(any("YYYY-MM-DD" in i for i in issues))
        self.assertEqual(sum("check this claim" in i for i in issues), 2)


if __name__ == "__main__":
    unittest.main()
