"""Read-only Codex tool adapter over the current UI's bound material reader.

The host supplies LocalReuse, never a browser path or an alternate project pin.
Installing these tools does not install ChatService, authorize a turn, or load
the old chat/budget stores. Future authorized ChatService wiring must use this
adapter to include the current sealed review beside the retained source index.
"""
from copy import deepcopy

READ_ACTIONS = frozenset({'state', 'materials', 'read_paper', 'read_saved_stage', 'read_material'})


class LocalReuseChatTools:
    def __init__(self, reader):
        self.reader = reader

    def context(self, project, stage):
        session = self.reader.session(project, stage, self.reader.pin)
        return self.reader._context(session)

    def specs(self):
        tools = deepcopy(self.reader.tools.specs())
        for tool in tools:
            choices = tool['inputSchema']['properties']['action']['enum']
            tool['inputSchema']['properties']['action']['enum'] = [a for a in choices if a in READ_ACTIONS]
        return tools

    def validate(self, session, args):
        if (type(args) is not dict or set(args) != {'action', 'id', 'note'}
                or not all(type(v) is str for v in args.values())
                or args['action'] not in READ_ACTIONS or args['note']
                or len(args['id']) > 240):
            raise ValueError('local-chat-read-arguments-rejected')
        bound = self.reader.session(session['project_ref'], session['stage'], session['project_pin'])
        context = self.reader._context(bound)
        if args['action'] not in context['supported_actions']:
            raise ValueError('local-chat-read-stage-not-supported')
        return context

    @staticmethod
    def writes(_args):
        return False

    def call(self, session, args):
        self.validate(session, args)
        return self.reader.read(session['project_ref'], session['stage'], session['project_pin'],
                                args['action'], args['id'])
