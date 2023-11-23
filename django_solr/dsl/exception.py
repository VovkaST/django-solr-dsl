from pysolr import SolrError


class NotFoundError(SolrError):
    pass


class MultipleResultError(SolrError):
    pass
