import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
import sunbear as sb
from sunbear import f
from sunbear._schema_html import _COPY


class Buttons(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.selectors = []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'button': self.selectors.append(attrs['data-selector'])


class SchemaSelectorTests(unittest.TestCase):
    def test_nested_literal_keys_and_list_traversal(self):
        row = {'author': {'literal.key': 1}, 'posts': [{'text': 'a'}, {'text': 'b'}], 'str': 2}
        html = sb.Schema.from_record(row)._repr_html_()
        selectors = Buttons(html).selectors
        self.assertIn("f['author']['literal.key']", selectors)
        self.assertIn("f['posts'][...]['text']", selectors)
        tree = sb.DataTree.from_records([row])
        expression = eval("f['posts'][...]['text']", {'f': f})
        self.assertEqual(tree.select(expression.as_('texts')).one(), {'texts': ['a', 'b']})
        for code in selectors:
            self.assertTrue(tree.select(eval(code, {'f': f})).one())
    def test_html_and_python_escaping(self):
        key = '\"><script>alert(1)</script>\n\\\''
        schema = sb.Schema(sb.Schema.from_record({key:1}).root, name='<img src=x onerror=alert(1)>')
        html = schema._repr_html_()
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        expression = eval(Buttons(html).selectors[0], {'f': f})
        self.assertEqual(sb.DataTree.from_records([{key:1}]).select(value=expression).one(), {'value':1})
        self.assertIn('Copyable selectors', html)
    def test_collapsed_and_empty(self):
        html = sb.Schema.from_record({'a':{'b':1}})._repr_html_impl(collapsed=True)
        self.assertNotIn('<details open>', html)
        self.assertIn('(empty)', sb.Schema.from_record({})._repr_html_())
    @unittest.skipUnless(shutil.which('node'), 'Node is optional for clipboard interaction tests')
    def test_clipboard_success_denial_and_fallback(self):
        script = '''
const handler = new Function('event', 'navigator', 'document', HANDLER);
async function check(mode) {
 let copied, prevented=0;
 const status = {textContent:''};
 const input = {hidden:true,focus(){},select(){}};
 const button = {dataset:{selector:"f['literal.key']"},focus(){},parentElement:{querySelector(s){return s==='input'?input:status;}}};
 const navigator = mode==='legacy' ? {} : {clipboard:{writeText(value){ copied=value; return mode==='denied'?Promise.reject(Error('denied')):Promise.resolve();}}};
 handler.call(button,{preventDefault(){prevented++;},stopPropagation(){prevented++;}},navigator,{execCommand(){return mode==='legacy';}});
 await Promise.resolve();
 if(prevented!==2) throw Error('branch toggle was not prevented');
 if(mode==='denied') { if(input.hidden || !status.textContent.includes('Select')) throw Error('manual fallback missing'); }
 else if(status.textContent!=='Copied!' || !input.hidden) throw Error('success feedback missing');
 if(mode==='modern' && copied!==button.dataset.selector) throw Error('wrong selector copied');
}
(async()=>{for(const mode of ['modern','denied','legacy'])await check(mode);})().catch(e=>{console.error(e);process.exit(1);});
'''.replace('HANDLER', json.dumps(_COPY))
        subprocess.run(['node','-e',script],check=True)
