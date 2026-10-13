import hashlib

from depscope.sources.advisories import AdvisoryRevision


def alias_group_key(identifiers: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(identifiers)).encode()).hexdigest()


def alias_groups(records: tuple[AdvisoryRevision,...]) -> dict[str,tuple[str,...]]:
    parent={}
    def find(item):
        parent.setdefault(item,item)
        while parent[item] != item:
            parent[item]=parent[parent[item]]
            item=parent[item]
        return item
    active=tuple(record for record in records if not record.withdrawn)
    for record in active:
        identifiers=(record.id,)+record.aliases
        root=find(record.id)
        for identifier in identifiers:
            other=find(identifier)
            if other != root:
                parent[other]=root
    groups={}
    for identifier in parent:
        groups.setdefault(find(identifier),set()).add(identifier)
    return {record.id:tuple(sorted(groups[find(record.id)])) for record in active}
