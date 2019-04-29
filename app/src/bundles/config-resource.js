import { createAsyncResourceBundle, createSelector } from 'redux-bundler'
import * as yaml from 'yaml'

const bundle = createAsyncResourceBundle({
  name: 'configResource',
  getPromise: () => {
    return fetch('audit-sources.yaml').then(response => response.text()).then(text => yaml.parse(text, 'utf8'))
  }
})

bundle.reactConfigResourceFetch = createSelector(
  'selectConfigResourceShouldUpdate',
  (shouldUpdate) => {
    if (!shouldUpdate) return
    return { actionCreator: 'doFetchConfigResource' }
  }
)

export default bundle