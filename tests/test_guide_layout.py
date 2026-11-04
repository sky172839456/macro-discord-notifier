import copy,unittest
from unittest.mock import patch
import guide_layout as g

class GuideLayout(unittest.TestCase):
    def test_visible_homepage_has_no_slash_and_layout_is_repeatable(self):
        original='說明\n\n**分享社群**\nWV官網：https://www.wviewture.com/'
        result=g.layout(original)
        self.assertIn('[https://www.wviewture.com](https://www.wviewture.com/)',result)
        self.assertIn(g.LINE,result);self.assertEqual(g.layout(result),result)

    def test_wrong_message_blocks_before_any_update(self):
        env={'DISCORD_WEBHOOK_URL':'https://discord.com/api/webhooks/123/TEST','APPLY_GUIDE_LAYOUT':'true'}
        calls=[]
        def api(url,changes=None):
            calls.append(changes)
            if '/messages/' in url:return {'id':'wrong','pinned':True,'content':'guide'}
            return {'id':'123','guild_id':'1524947809499877486','channel_id':g.EXPECTED['DISCORD_WEBHOOK_URL'],'type':1}
        with patch.object(g,'TARGETS',g.TARGETS[:1]),self.assertRaises(ValueError):g.run(env,call=api)
        self.assertTrue(all(x is None for x in calls))

    def test_apply_requires_identical_preflight_plan(self):
        env={'DISCORD_WEBHOOK_URL':'https://discord.com/api/webhooks/123/TEST','APPLY_GUIDE_LAYOUT':'true','EXPECTED_GUIDE_PLAN_HASH':'wrong'}
        calls=[]
        def api(url,changes=None):
            calls.append(changes)
            if '/messages/' in url:return {'id':g.TARGETS[0][1],'channel_id':g.EXPECTED['DISCORD_WEBHOOK_URL'],'webhook_id':'123','pinned':True,'content':'介紹\n\n**來源**\nhttps://example.com'}
            return {'id':'123','guild_id':'1524947809499877486','channel_id':g.EXPECTED['DISCORD_WEBHOOK_URL'],'type':1}
        with patch.object(g,'TARGETS',g.TARGETS[:1]),self.assertRaises(ValueError):g.run(env,call=api)
        self.assertTrue(all(x is None for x in calls))
