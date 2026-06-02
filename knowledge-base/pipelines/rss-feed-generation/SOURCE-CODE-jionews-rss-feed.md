# Source Code: thenewj-com/jionews-rss-feed
> Auto-synced from GitHub on 2026-04-14 11:54 UTC
> Branch: `main` | Role: RSS feed generation service

## Repository Structure
```
.circleci/config.yml
.env.sample
.eslintrc.js
.gitignore
.npmrc
.nvmrc
.nycrc.json
Dockerfile
Jenkins.groovy
Jenkinsfile
LICENSE
Procfile
README.md
k8s/development/deployment.yaml
k8s/development/hpa.yaml
k8s/development/service.yaml
k8s/production/deployment.yaml
k8s/production/hpa.yaml
k8s/production/service.yaml
k8s/staging/deployment.yaml
k8s/staging/hpa.yaml
k8s/staging/service.yaml
package-lock.json
package.json
preprodjenkins.groovy
prodjenkins.groovy
public/favicon.ico
src/app/db.js
src/app/index.js
src/app/server.js
src/config/db.js
src/config/errors/index.js
src/config/errors/notFoundError.js
src/config/errors/validationError.js
src/config/index.js
src/config/middlewares/index.js
src/config/middlewares/req-res-interceptor.js
src/config/middlewares/rollbar.js
src/config/middlewares/sentry.js
src/constants/db.js
src/constants/i18n.js
src/constants/index.js
src/constants/server.js
src/controllers/index.js
src/controllers/user/index.js
src/controllers/user/login.js
src/controllers/user/logout.js
src/controllers/user/verifyOtp.js
src/index.js
src/middlewares/auth.js
src/middlewares/index.js
src/models/auth.js
src/models/index.js
src/models/user.js
src/routes/index.js
src/routes/user/index.js
src/routes/user/isLoggedIn.js
src/routes/user/login.js
src/routes/user/logout.js
src/routes/user/verifyOtp.js
src/services/index.js
src/services/wrapperService.js
src/utilities/bootstrap.js
src/utilities/index.js
src/utilities/logger.js
src/utilities/response.js
src/utilities/universalFunctions.js
src/validations/index.js
src/validations/user.js
```

## `README.md`
```markdown
# nodejs-rest-boilerplate

A NodeJs application with Express framework, MongoDb as database, Mongoose as ODM.  
It uses Joi for schema validation.  
It uses eslint, husky, and lint-staged for code-linting purposes.  
It contains a simple routing example.

## Tech Stack

* [Node.js] - Free, open-sourced, cross-platform JavaScript run-time environment
* [Express] - Fast, unopinionated, minimalist web framework for Node.js 
* [Mongoose] - Elegant MongoDB ODM for node.js
* [Joi] - Schema description language and data validator
* [Postman] - Collaboration Platform for API Development

**nodejs-rest-boilerplate** itself is **open source** with a [public repository][nodejs-rest-boilerplate] on GitHub.

## Running it

> `yarn`

> Copy *.env.sample* as **.env** to root directory, and put appropriate values in it. It is an optional step, application will run using default values if *.env* is not found.

> `yarn start` or `yarn run dev`

## License

AGPL-3.0-or-later

## Meet The Makers

[Shrikant Aher]


[Suraj Singh] - DevOps at work 👀

[Shrikant Aher]: <https://www.linkedin.com/in/shrikantaher/>
[Suraj Singh]: <https://www.linkedin.com/in/suraj-singh-n2711//>
[Node.js]: <https://nodejs.dev/>
[Express]: <http://expressjs.com/>
[Mongoose]: <https://mongoosejs.com/>
[Joi]: <https://joi.dev/>
[Postman]: <https://www.postman.com/>
[nodejs-rest-boilerplate]: <https://github.com/thenewj-com/nodejs-rest-boilerplate/>
```

## `Dockerfile`
```
FROM node:18-alpine
WORKDIR /src
COPY .npmrc .npmrc
COPY package.json /src/package.json
COPY package-lock.json /src/package-lock.json
COPY yarn.lock /src/yarn.lock
RUN npm install
COPY src src
CMD ["npm", "run", "start"]
```
