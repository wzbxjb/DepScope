"""Only the external OSV HTTP boundary is replaced; parsing/storage stay real."""
import httpx

from depscope.sources.osv import OsvClient
from depscope.sources.records import RecordStore


class MockOsv:
    def __init__(self, router, root):
        self.router=router
        self.http=httpx.AsyncClient()
        self.client=OsvClient(RecordStore(root),self.http)

    def batch(self,rows):
        self.router.post("https://api.osv.dev/v1/querybatch").respond(200,json={"results":rows})

    def single_page(self,token,row):
        def response(request):
            import json
            assert json.loads(request.content)["page_token"] == token
            return httpx.Response(200,json=row)
        self.router.post("https://api.osv.dev/v1/query").mock(side_effect=response)
