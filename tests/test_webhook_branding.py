import copy
import unittest
from unittest.mock import patch
import webhook_branding as brand


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.keys=('DISCORD_MATERIAL_WEBHOOK_URL', 'DISCORD_CRYPTO_NEWS_WEBHOOK_URL')
        self.env={k:'https://discord.com/api/webhooks/'+str(i+1)+'/TEST' for i,k in enumerate(self.keys)}
        self.calls=[]
        self.metadata={self.env[k]: {'id':str(i+1), 'type':1, 'guild_id':brand.GUILD,
                       'channel_id':brand.EXPECTED[k], 'name':'old', 'avatar':None} for i,k in enumerate(self.keys)}

    def api(self,url,changes=None):
        self.calls.append((url,changes))
        if changes is not None:
            self.assertEqual(set(changes), {'name','avatar'})
            self.metadata[url].update(name=changes['name'],avatar='new-avatar-hash')
        return copy.deepcopy(self.metadata[url])

    def test_dry_audit_never_mutates(self):
        with patch.object(brand,'SECRETS',self.keys):
            result=brand.run(self.env,call=self.api)
        self.assertTrue(all(changes is None for _,changes in self.calls))
        self.assertEqual(result['message_sends'],0)
        self.assertEqual(result['message_edits'],0)

    def test_wrong_later_destination_prevents_all_patches(self):
        self.metadata[self.env[self.keys[1]]]['channel_id']='wrong'
        with patch.object(brand,'SECRETS',self.keys), self.assertRaises(ValueError):
            brand.run(self.env,apply=True,call=self.api)
        self.assertTrue(all(changes is None for _,changes in self.calls))

    def test_apply_only_updates_display_fields_and_reads_back(self):
        with patch.object(brand,'SECRETS',self.keys):
            result=brand.run(self.env,apply=True,call=self.api)
        self.assertEqual(sum(changes is not None for _,changes in self.calls),2)
        self.assertTrue(all(r['name_matches'] and r['avatar_set'] for r in result['webhooks']))

    def test_missing_secret_and_wrong_asset_cannot_mutate(self):
        for env,asset in (({},None),(self.env,b'wrong')):
            with patch.object(brand,'SECRETS',self.keys), self.assertRaises(ValueError):
                brand.run(env,apply=True,call=self.api,asset=asset)
        self.assertEqual(self.calls,[])

    def test_shared_webhook_alias_is_patched_only_once(self):
        keys=('DISCORD_CRYPTO_NEWS_WEBHOOK_URL','DISCORD_BREAKING_NEWS_WEBHOOK_URL')
        env={k:self.env[self.keys[1]] for k in keys}
        with patch.object(brand,'SECRETS',keys):
            brand.run(env,apply=True,call=self.api)
        self.assertEqual(sum(changes is not None for _,changes in self.calls),1)

    def test_bad_readback_stops_instead_of_claiming_success(self):
        def rejected(url,changes=None):
            if changes is not None:
                return {**self.metadata[url],'avatar':'different'}
            return self.api(url,changes)
        with patch.object(brand,'SECRETS',self.keys), self.assertRaises(ValueError):
            brand.run(self.env,apply=True,call=rejected)


if __name__=='__main__': unittest.main()
